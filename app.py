import hmac
import io
import mimetypes
import os
import re
import secrets
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from flask import (Flask, abort, flash, g, redirect, render_template, request, send_file,
                   session, url_for)
from flask_sqlalchemy import SQLAlchemy
from openpyxl.styles import Border, Side
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from werkzeug.exceptions import HTTPException

from config import BASE_DIR, USAR_HTTPS, segredo, url_do_banco
from email_envio import enviar_codigo, validar_config as validar_smtp
from seguranca import (SENHA_MAX, TextoCriptografado, cifrar_bytes, codigo_confere, decifrar_bytes,
                       gerar_codigo, hash_codigo, hash_senha, indice_cego, normalizar, validar_chaves,
                       verificar_senha)

INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')

app = Flask(__name__, instance_path=INSTANCE_DIR)
os.makedirs(app.instance_path, exist_ok=True)

validar_chaves()  # falha logo na partida se faltar alguma chave no .env
validar_smtp()    # e se o e-mail (SMTP) não estiver configurado

URL_BANCO = url_do_banco()
opcoes_motor = {'pool_pre_ping': True, 'pool_recycle': 280}
if URL_BANCO.startswith('postgresql'):
    opcoes_motor['connect_args'] = {'sslmode': 'require'}  # conexão com o Supabase sempre cifrada

app.config['SECRET_KEY'] = segredo('CASTRAMOVEL_SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = URL_BANCO
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = opcoes_motor
app.config['UPLOAD_FOLDER'] = os.path.join(app.instance_path, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = USAR_HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
app.config['JSON_AS_ASCII'] = False

db = SQLAlchemy(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

EXTENSOES = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'doc', 'docx', 'odt', 'xls', 'xlsx', 'txt'}
EXIBIR_NO_NAVEGADOR = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'}
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def enc(coluna):
    """Coluna criptografada (AES-256-GCM). O nome da coluna entra como dado autenticado."""
    return TextoCriptografado(coluna)


# ---------------------------------------------------------------------------
# Modelos. Dados pessoais ficam criptografados no banco; só o servidor (com a chave do .env) lê.
# Ficam em claro apenas: ids, datas/horas dos agendamentos e o nome de login.
# ---------------------------------------------------------------------------
class Usuario(db.Model):
    __tablename__ = 'usuario'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(enc('usuario.email'), nullable=True)  # recebe o código de verificação do login

    def definir_email(self, email):
        self.email = email.strip().lower()


class VerificacaoLogin(db.Model):
    """Tentativa de login esperando o código do e-mail. Guarda só o hash do código."""
    __tablename__ = 'verificacao_login'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)  # fica na sessão do navegador
    codigo_hash = db.Column(db.String(64), nullable=False)
    tentativas = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(db.DateTime, nullable=False)
    expira_em = db.Column(db.DateTime, nullable=False)


class Tutor(db.Model):
    __tablename__ = 'tutor'
    id = db.Column(db.Integer, primary_key=True)
    nome_completo = db.Column(enc('tutor.nome_completo'), nullable=False)
    telefone = db.Column(enc('tutor.telefone'), nullable=False)
    cpf = db.Column(enc('tutor.cpf'), nullable=False)
    cpf_idx = db.Column(db.String(64), unique=True, nullable=False)  # HMAC do CPF: só para evitar duplicidade
    endereco = db.Column(enc('tutor.endereco'), nullable=False)
    numero = db.Column(enc('tutor.numero'), nullable=False)
    documentos = db.relationship('Documento', backref='tutor', lazy=True)
    animais = db.relationship('Animal', backref='tutor', lazy=True)

    def definir_cpf(self, cpf):
        self.cpf = cpf.strip()
        self.cpf_idx = indice_cego(so_digitos(cpf), 'tutor.cpf')


class Animal(db.Model):
    __tablename__ = 'animal'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(enc('animal.nome'), nullable=False)
    raca = db.Column(enc('animal.raca'), nullable=False)
    sexo = db.Column(enc('animal.sexo'), nullable=False)  # macho ou femea
    microchip = db.Column(enc('animal.microchip'), nullable=True)
    microchip_idx = db.Column(db.String(64), unique=True, nullable=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=False)

    def definir_microchip(self, valor):
        limpo = re.sub(r'\s', '', valor or '').upper()
        self.microchip = limpo or None
        self.microchip_idx = indice_cego(limpo, 'animal.microchip')


class Documento(db.Model):
    __tablename__ = 'documento'
    id = db.Column(db.Integer, primary_key=True)
    nome_arquivo = db.Column(enc('documento.nome_arquivo'), nullable=False)  # nome original, usado na tela
    caminho = db.Column(db.String(200), nullable=False)  # nome aleatório do arquivo cifrado em uploads/
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=False)


class Agendamento(db.Model):
    __tablename__ = 'agendamento'
    __table_args__ = (db.UniqueConstraint('data', 'hora', name='uq_agendamento_data_hora'),)
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    animal = db.relationship('Animal', backref='agendamentos')


if URL_BANCO.startswith('sqlite'):
    # Só para testes locais. No Supabase as tabelas vêm do supabase_schema.sql (com RLS ligado).
    with app.app_context():
        db.create_all()


# ---------------------------------------------------------------------------
# Utilidades de validação
# ---------------------------------------------------------------------------
def so_digitos(texto):
    return re.sub(r'\D', '', texto or '')


def cpf_valido(cpf):
    d = so_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(d[n]) * (i + 1 - n) for n in range(i))
        if (soma * 10) % 11 % 10 != int(d[i]):
            return False
    return True


def email_valido(email):
    if not email or len(email) > 254 or any(c in email for c in '<>"\'(),;:\\'):
        return False
    return re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) is not None


def mascarar_email(email):
    nome, _, dominio = email.partition('@')
    return f'{nome[:1]}***@{dominio}'


def inteiro(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        abort(400)


def ler_tutor(form):
    campos = {c: form.get(c, '').strip() for c in ('nome', 'telefone', 'cpf', 'endereco', 'numero')}
    limites = {'nome': 100, 'telefone': 20, 'cpf': 14, 'endereco': 200, 'numero': 10}
    if not all(campos.values()):
        return campos, 'Preencha todos os campos.'
    if any(len(campos[c]) > m for c, m in limites.items()):
        return campos, 'Algum campo ultrapassa o tamanho permitido.'
    if not cpf_valido(campos['cpf']):
        return campos, 'CPF inválido.'
    return campos, None


def ler_animal(form):
    campos = {c: form.get(c, '').strip() for c in ('nome', 'raca', 'sexo', 'microchip')}
    if not (campos['nome'] and campos['raca']) or campos['sexo'] not in ('macho', 'femea'):
        return campos, 'Preencha nome, raça e sexo.'
    if len(campos['nome']) > 50 or len(campos['raca']) > 50 or len(campos['microchip']) > 20:
        return campos, 'Algum campo ultrapassa o tamanho permitido.'
    return campos, None


# ---------------------------------------------------------------------------
# Segurança de requisição: CSRF, login, cabeçalhos
# ---------------------------------------------------------------------------
def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def proteger_csrf():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        enviado = request.form.get('csrf_token', '') or request.headers.get('X-CSRF-Token', '')
        esperado = session.get('csrf', '')
        if not esperado or not hmac.compare_digest(enviado, esperado):
            abort(400)


FALHAS = {}  # ip -> [falhas seguidas, bloqueado até]
MAX_FALHAS = 5
BLOQUEIO = timedelta(minutes=5)
SENHA_MIN = 10


def bloqueado(ip):
    registro = FALHAS.get(ip)
    return bool(registro and registro[1] and registro[1] > datetime.now())


def registrar_falha(ip):
    registro = FALHAS.setdefault(ip, [0, None])
    registro[0] += 1
    if registro[0] >= MAX_FALHAS:
        FALHAS[ip] = [0, datetime.now() + BLOQUEIO]


def validar_senha(senha, confirmacao):
    if len(senha) < SENHA_MIN:
        return f'A senha deve ter pelo menos {SENHA_MIN} caracteres.'
    if len(senha) > SENHA_MAX:
        return 'Senha longa demais.'
    if senha != confirmacao:
        return 'As senhas não conferem.'
    return None


def destino_seguro(destino):
    if destino and destino.startswith('/') and not destino.startswith('//') and '\\' not in destino:
        return destino
    return url_for('index')


@app.before_request
def exigir_login():
    endpoint = request.endpoint
    if endpoint is None or endpoint == 'static':
        return None
    g.usuario = db.session.get(Usuario, session['usuario_id']) if session.get('usuario_id') else None
    if g.usuario:
        return redirect(url_for('index')) if endpoint == 'primeiro_acesso' else None
    sem_usuarios = Usuario.query.count() == 0
    if sem_usuarios:
        return None if endpoint == 'primeiro_acesso' else redirect(url_for('primeiro_acesso'))
    if endpoint == 'primeiro_acesso':
        return redirect(url_for('login'))
    if endpoint not in ('login', 'verificar', 'reenviar_codigo'):
        session.clear()
        return redirect(url_for('login', proximo=request.path if request.method == 'GET' else None))
    return None


CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")


@app.after_request
def cabecalhos(resposta):
    resposta.headers['X-Content-Type-Options'] = 'nosniff'
    resposta.headers['X-Frame-Options'] = 'DENY'
    resposta.headers['Referrer-Policy'] = 'no-referrer'
    resposta.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    resposta.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    if resposta.mimetype == 'text/html':
        resposta.headers['Content-Security-Policy'] = CSP
    if USAR_HTTPS:
        resposta.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    if request.endpoint != 'static':
        resposta.headers['Cache-Control'] = 'no-store'
        resposta.headers['Pragma'] = 'no-cache'
    return resposta


@app.context_processor
def contexto():
    return {'usuario_atual': g.get('usuario')}


MENSAGENS_ERRO = {
    400: 'Requisição inválida ou sessão expirada. Volte, recarregue a página e tente de novo.',
    403: 'Acesso negado.',
    404: 'Página não encontrada.',
    405: 'Ação não permitida.',
    413: 'Arquivo grande demais (máximo de 16 MB).',
}


@app.errorhandler(Exception)
def tratar_erro(erro):
    if isinstance(erro, HTTPException):
        codigo, mensagem = erro.code, MENSAGENS_ERRO.get(erro.code, 'Não foi possível concluir a solicitação.')
    else:
        app.logger.exception('Erro inesperado')  # o detalhe fica só no log do servidor
        db.session.rollback()
        codigo, mensagem = 500, 'Erro interno. Tente novamente; se continuar, avise o responsável pelo sistema.'
    return render_template('erro.html', codigo=codigo, mensagem=mensagem), codigo


# ---------------------------------------------------------------------------
# Login e senha
# ---------------------------------------------------------------------------
EXPIRA_CODIGO = timedelta(minutes=10)
MAX_TENTATIVAS_CODIGO = 5
INTERVALO_REENVIO = timedelta(seconds=60)


def agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iniciar_verificacao(usuario):
    """Gera o código, guarda só o hash e envia por e-mail. O login só termina em /verificar."""
    VerificacaoLogin.query.filter(or_(VerificacaoLogin.usuario_id == usuario.id,
                                      VerificacaoLogin.expira_em < agora())).delete(synchronize_session=False)
    codigo, token = gerar_codigo(), secrets.token_urlsafe(32)
    verificacao = VerificacaoLogin(usuario_id=usuario.id, token=token, codigo_hash=hash_codigo(token, codigo),
                                   criado_em=agora(), expira_em=agora() + EXPIRA_CODIGO)
    db.session.add(verificacao)
    db.session.commit()
    try:
        enviar_codigo(usuario.email, codigo, int(EXPIRA_CODIGO.total_seconds() // 60))
    except Exception:  # noqa: BLE001
        app.logger.exception('Falha ao enviar o e-mail de verificação')
        db.session.delete(verificacao)
        db.session.commit()
        flash('Não foi possível enviar o e-mail agora. Tente de novo em instantes ou avise o responsável.', 'error')
        return False
    session.clear()
    session['verif'] = token
    return True


def desafio_atual():
    token = session.get('verif')
    verificacao = VerificacaoLogin.query.filter_by(token=token).first() if token else None
    if verificacao and verificacao.expira_em < agora():
        db.session.delete(verificacao)
        db.session.commit()
        return None
    return verificacao


@app.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        nome = request.form.get('usuario', '').strip().lower()
        email = request.form.get('email', '').strip()
        erro = None if nome and len(nome) <= 50 else 'Informe um nome de usuário (até 50 caracteres).'
        erro = erro or (None if email_valido(email) else 'Informe um e-mail válido.')
        erro = erro or validar_senha(request.form.get('senha', ''), request.form.get('confirmacao', ''))
        if erro:
            flash(erro, 'error')
        else:
            usuario = Usuario(nome=nome, senha_hash=hash_senha(request.form['senha']))
            usuario.definir_email(email)
            db.session.add(usuario)
            db.session.commit()
            if iniciar_verificacao(usuario):  # confirma que o e-mail funciona antes de liberar o acesso
                flash(f'Usuário criado. Enviamos um código para {mascarar_email(usuario.email)}.', 'success')
                return redirect(url_for('verificar'))
            return redirect(url_for('login'))
    return render_template('primeiro_acesso.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.usuario:
        return redirect(url_for('index'))
    if request.method == 'POST':
        ip = request.remote_addr
        if bloqueado(ip):
            flash('Muitas tentativas. Aguarde alguns minutos e tente de novo.', 'error')
            return render_template('login.html'), 429
        nome = request.form.get('usuario', '').strip().lower()
        senha = request.form.get('senha', '')
        usuario = Usuario.query.filter_by(nome=nome).first()
        ok, atualizar = verificar_senha(senha, usuario.senha_hash if usuario else None)
        if usuario and ok:
            if atualizar:  # hash antigo (sem pepper) é regravado no formato novo
                usuario.senha_hash = hash_senha(senha)
                db.session.commit()
            FALHAS.pop(ip, None)
            if bloqueado(f'cod:{usuario.id}'):
                flash('Muitos códigos incorretos para este usuário. Aguarde alguns minutos.', 'error')
                return render_template('login.html'), 429
            if not usuario.email:
                flash('Este usuário não tem e-mail cadastrado. Peça ao responsável: '
                      'python usuarios.py email NOME', 'error')
                return render_template('login.html')
            if iniciar_verificacao(usuario):
                flash(f'Enviamos um código de 6 dígitos para {mascarar_email(usuario.email)}.', 'success')
                return redirect(url_for('verificar'))
            return render_template('login.html')
        registrar_falha(ip)
        flash('Usuário ou senha incorretos.', 'error')
    return render_template('login.html')


@app.route('/verificar', methods=['GET', 'POST'])
def verificar():
    if g.usuario:
        return redirect(url_for('index'))
    verificacao = desafio_atual()
    if verificacao is None:
        flash('A verificação expirou. Entre novamente.', 'error')
        return redirect(url_for('login'))
    usuario = db.session.get(Usuario, verificacao.usuario_id)
    if request.method == 'POST':
        chave = f'cod:{usuario.id}'
        if bloqueado(chave):
            flash('Muitos códigos incorretos. Aguarde alguns minutos.', 'error')
            return render_template('verificar.html', email=mascarar_email(usuario.email)), 429
        codigo = re.sub(r'\D', '', request.form.get('codigo', ''))
        if codigo_confere(verificacao.token, codigo, verificacao.codigo_hash):
            db.session.delete(verificacao)
            db.session.commit()
            FALHAS.pop(chave, None)
            session.clear()
            session['usuario_id'] = usuario.id
            session.permanent = True
            return redirect(destino_seguro(request.args.get('proximo')))
        registrar_falha(chave)
        verificacao.tentativas += 1
        if verificacao.tentativas >= MAX_TENTATIVAS_CODIGO:
            db.session.delete(verificacao)
            db.session.commit()
            session.clear()
            flash('Muitas tentativas com código incorreto. Entre novamente.', 'error')
            return redirect(url_for('login'))
        db.session.commit()
        flash('Código incorreto.', 'error')
    return render_template('verificar.html', email=mascarar_email(usuario.email))


@app.route('/reenviar_codigo', methods=['POST'])
def reenviar_codigo():
    verificacao = desafio_atual()
    if verificacao is None:
        return redirect(url_for('login'))
    if agora() - verificacao.criado_em < INTERVALO_REENVIO:
        flash('Aguarde um minuto para pedir outro código.', 'error')
        return redirect(url_for('verificar'))
    usuario = db.session.get(Usuario, verificacao.usuario_id)
    if iniciar_verificacao(usuario):
        flash('Enviamos um novo código.', 'success')
        return redirect(url_for('verificar'))
    return redirect(url_for('login'))


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/alterar_senha', methods=['GET', 'POST'])
def alterar_senha():
    if request.method == 'POST':
        ok, _ = verificar_senha(request.form.get('atual', ''), g.usuario.senha_hash)
        if not ok:
            flash('A senha atual está incorreta.', 'error')
        else:
            erro = validar_senha(request.form.get('senha', ''), request.form.get('confirmacao', ''))
            if erro:
                flash(erro, 'error')
            else:
                g.usuario.senha_hash = hash_senha(request.form['senha'])
                db.session.commit()
                flash('Senha alterada.', 'success')
                return redirect(url_for('index'))
    return render_template('alterar_senha.html')


# ---------------------------------------------------------------------------
# Documentos (arquivos cifrados no disco; o nome em uploads/ é aleatório)
# ---------------------------------------------------------------------------
def salvar_documentos(arquivos, tutor):
    recusados = 0
    for arquivo in arquivos:
        if not arquivo.filename:
            continue
        original = os.path.basename(arquivo.filename.replace('\\', '/'))[:100]
        extensao = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
        conteudo = arquivo.read()
        if extensao not in EXTENSOES or not conteudo:
            recusados += 1
            continue
        guardado = f'{uuid.uuid4().hex}.enc'
        with open(os.path.join(app.config['UPLOAD_FOLDER'], guardado), 'wb') as f:
            f.write(cifrar_bytes(conteudo, f'documento.arquivo:{guardado}'))
        db.session.add(Documento(nome_arquivo=original, caminho=guardado, tutor_id=tutor.id))
    db.session.commit()
    if recusados:
        flash(f'{recusados} arquivo(s) não enviado(s). Use PDF, imagem, Word, Excel ou texto.', 'error')


@app.route('/documento/<int:id>')
def baixar_documento(id):
    doc = db.get_or_404(Documento, id)
    guardado = os.path.basename(doc.caminho.replace('\\', '/'))
    caminho = os.path.join(app.config['UPLOAD_FOLDER'], guardado)
    if not os.path.isfile(caminho):
        abort(404)
    with open(caminho, 'rb') as f:
        conteudo = decifrar_bytes(f.read(), f'documento.arquivo:{guardado}')
    nome = doc.nome_arquivo
    extensao = nome.rsplit('.', 1)[-1].lower() if '.' in nome else ''
    return send_file(io.BytesIO(conteudo), mimetype=mimetypes.guess_type(nome)[0] or 'application/octet-stream',
                     as_attachment=extensao not in EXIBIR_NO_NAVEGADOR, download_name=nome)


# ---------------------------------------------------------------------------
# Buscas. Os campos são criptografados, então o filtro é feito aqui, depois de descriptografar
# em memória. Para o volume de uma clínica isso é rápido.
# ---------------------------------------------------------------------------
def todos_tutores():
    return sorted(Tutor.query.all(), key=lambda t: normalizar(t.nome_completo))


def buscar_tutores(busca):
    q, digitos = normalizar(busca), so_digitos(busca)
    return [t for t in todos_tutores()
            if q in normalizar(t.nome_completo) or (digitos and digitos in so_digitos(t.cpf))]


def buscar_animais(busca):
    q = normalizar(busca)
    animais = Animal.query.options(joinedload(Animal.tutor)).all()
    animais = [a for a in animais if q in normalizar(a.nome) or q in normalizar(a.microchip or '')]
    return sorted(animais, key=lambda a: normalizar(a.nome))


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    proximos = (Agendamento.query.options(joinedload(Agendamento.animal).joinedload(Animal.tutor))
                .filter(Agendamento.data >= date.today())
                .order_by(Agendamento.data, Agendamento.hora).limit(10).all())
    return render_template('index.html', proximos=proximos,
                           total_tutores=Tutor.query.count(), total_animais=Animal.query.count())


@app.route('/cadastrar_tutor', methods=['GET', 'POST'])
def cadastrar_tutor():
    if request.method == 'POST':
        dados, erro = ler_tutor(request.form)
        if not erro:
            tutor = Tutor(nome_completo=dados['nome'], telefone=dados['telefone'],
                          endereco=dados['endereco'], numero=dados['numero'])
            tutor.definir_cpf(dados['cpf'])
            db.session.add(tutor)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                erro = 'Já existe um tutor cadastrado com esse CPF.'
        if erro:
            flash(erro, 'error')
            return render_template('cadastrar_tutor.html')
        salvar_documentos(request.files.getlist('documentos'), tutor)
        flash('Tutor cadastrado com sucesso!', 'success')
        return redirect(url_for('index'))
    return render_template('cadastrar_tutor.html')


@app.route('/cadastrar_animal', methods=['GET', 'POST'])
def cadastrar_animal():
    search = request.args.get('search', '')
    tutores = buscar_tutores(search) if search else todos_tutores()
    if request.method == 'POST':
        dados, erro = ler_animal(request.form)
        tutor = db.session.get(Tutor, inteiro(request.form.get('tutor_id')))
        if tutor is None:
            erro = 'Escolha um tutor.'
        if not erro:
            animal = Animal(nome=dados['nome'], raca=dados['raca'], sexo=dados['sexo'], tutor_id=tutor.id)
            animal.definir_microchip(dados['microchip'])
            db.session.add(animal)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                erro = 'Já existe um animal com esse microchip.'
        if erro:
            flash(erro, 'error')
            return render_template('cadastrar_animal.html', tutores=tutores, search=search)
        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('index'))
    return render_template('cadastrar_animal.html', tutores=tutores, search=search)


@app.route('/procurar_tutor', methods=['GET', 'POST'])
def procurar_tutor():
    tutores = []
    busca = ''
    if request.method == 'POST':
        busca = request.form.get('busca', '').strip()
        tutores = buscar_tutores(busca) if busca else []
    return render_template('procurar_tutor.html', tutores=tutores, busca=busca)


@app.route('/tutor/<int:id>', methods=['GET', 'POST'])
def tutor_perfil(id):
    tutor = db.get_or_404(Tutor, id)
    if request.method == 'POST':
        dados, erro = ler_tutor(request.form)
        if not erro:
            tutor.nome_completo, tutor.telefone = dados['nome'], dados['telefone']
            tutor.endereco, tutor.numero = dados['endereco'], dados['numero']
            tutor.definir_cpf(dados['cpf'])
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                erro = 'Já existe outro tutor cadastrado com esse CPF.'
        if erro:
            flash(erro, 'error')
        else:
            salvar_documentos(request.files.getlist('documentos'), tutor)
            flash('Perfil atualizado!', 'success')
    return render_template('tutor_perfil.html', tutor=tutor)


def salvar_animal(animal):
    dados, erro = ler_animal(request.form)
    if not erro:
        animal.nome, animal.raca, animal.sexo = dados['nome'], dados['raca'], dados['sexo']
        animal.definir_microchip(dados['microchip'])
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            erro = 'Já existe outro animal com esse microchip.'
    flash(erro or 'Animal atualizado!', 'error' if erro else 'success')


@app.route('/editar_animal/<int:id>', methods=['GET', 'POST'])
def editar_animal(id):
    animal = db.get_or_404(Animal, id)
    if request.method == 'POST':
        salvar_animal(animal)
    return render_template('editar_animal.html', animal=animal)


@app.route('/procurar_animal', methods=['GET', 'POST'])
def procurar_animal():
    animais = []
    busca = ''
    if request.method == 'POST':
        busca = request.form.get('busca', '').strip()
        animais = buscar_animais(busca) if busca else []
    return render_template('procurar_animal.html', animais=animais, busca=busca)


@app.route('/animal/<int:id>', methods=['GET', 'POST'])
def animal_perfil(id):
    animal = db.get_or_404(Animal, id)
    if request.method == 'POST':
        salvar_animal(animal)
    return render_template('animal_perfil.html', animal=animal)


@app.route('/agendamentos', methods=['GET', 'POST'])
def agendamentos():
    tutores = todos_tutores()
    selected_tutor = None
    animais = []
    if request.method == 'POST' and request.form.get('tutor_id'):
        selected_tutor = db.session.get(Tutor, inteiro(request.form.get('tutor_id')))
        if selected_tutor:
            animais = selected_tutor.animais
    return render_template('agendamentos.html', tutores=tutores, selected_tutor=selected_tutor, animais=animais)


@app.route('/agendar', methods=['POST'])
def agendar():
    try:
        data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
        hora = datetime.strptime(request.form['hora'], '%H:%M').time()
    except (KeyError, ValueError):
        abort(400)
    animal = db.get_or_404(Animal, inteiro(request.form.get('animal_id')))
    if data.weekday() >= 5:
        flash('Agendamentos apenas de segunda a sexta.', 'error')
    elif data < date.today():
        flash('Escolha hoje ou uma data futura.', 'error')
    elif Agendamento.query.filter_by(data=data, hora=hora).first():
        flash('Horário já ocupado!', 'error')
    else:
        db.session.add(Agendamento(data=data, hora=hora, animal_id=animal.id))
        try:
            db.session.commit()
            flash('Agendamento realizado!', 'success')
        except IntegrityError:  # duas pessoas no mesmo horário ao mesmo tempo
            db.session.rollback()
            flash('Horário já ocupado!', 'error')
    return redirect(url_for('agendamentos'))


# ---------------------------------------------------------------------------
# Relatórios. Os dados são descriptografados em memória só na hora de montar a planilha;
# nada em claro é gravado no disco.
# ---------------------------------------------------------------------------
BORDA = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))


def seguro_excel(valor):
    """Evita injeção de fórmula: texto começando com = + - @ viraria fórmula no Excel."""
    if isinstance(valor, str) and valor[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + valor
    return valor


def margens(planilha):
    for lado in ('left', 'right', 'top', 'bottom'):
        setattr(planilha.page_margins, lado, 0.5)
    planilha.page_margins.header = 0.3
    planilha.page_margins.footer = 0.3


@app.route('/gerar_excel_mes')
def gerar_excel_mes():
    try:
        ano = int(request.args.get('ano', date.today().year))
        mes = int(request.args.get('mes', date.today().month))
        inicio = datetime(ano, mes, 1)
    except (TypeError, ValueError):
        abort(400)
    fim = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    agendamentos = (Agendamento.query.options(joinedload(Agendamento.animal).joinedload(Animal.tutor))
                    .filter(Agendamento.data.between(inicio.date(), fim.date()))
                    .order_by(Agendamento.data, Agendamento.hora).all())
    if not agendamentos:
        flash('Não há agendamentos neste mês.', 'error')
        return redirect(url_for('relatorios'))

    por_dia = defaultdict(list)
    for ag in agendamentos:
        por_dia[ag.data].append(ag)

    colunas = ['Data', 'Hora', 'Animal', 'Raça', 'Sexo', 'Tutor', 'CPF Tutor']
    arquivo = io.BytesIO()
    with pd.ExcelWriter(arquivo, engine='openpyxl') as writer:
        for dia in sorted(por_dia):
            linhas = [dict.fromkeys(colunas, ''), dict(zip(colunas, colunas))]
            linhas[0]['Data'] = dia.strftime('%d/%m/%Y')
            for a in por_dia[dia]:
                linhas.append({'Data': dia.strftime('%d/%m/%Y'), 'Hora': str(a.hora),
                               'Animal': seguro_excel(a.animal.nome), 'Raça': seguro_excel(a.animal.raca),
                               'Sexo': a.animal.sexo, 'Tutor': seguro_excel(a.animal.tutor.nome_completo),
                               'CPF Tutor': seguro_excel(a.animal.tutor.cpf)})
            nome_aba = dia.strftime('%d-%m')
            pd.DataFrame(linhas).to_excel(writer, sheet_name=nome_aba, index=False)
            planilha = writer.sheets[nome_aba]
            for linha in planilha.iter_rows(min_row=1, max_row=len(linhas), min_col=1, max_col=7):
                for celula in linha:
                    celula.border = BORDA
            margens(planilha)
    arquivo.seek(0)
    return send_file(arquivo, as_attachment=True, download_name=f'agenda_{ano}_{mes}.xlsx', mimetype=XLSX)


@app.route('/gerar_excel_dia')
def gerar_excel_dia():
    data_str = request.args.get('data', date.today().isoformat())
    try:
        dia = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        abort(400)
    agendamentos = (Agendamento.query.options(joinedload(Agendamento.animal).joinedload(Animal.tutor))
                    .filter_by(data=dia).order_by(Agendamento.hora).all())
    linhas = [{'Hora': a.hora, 'Animal': seguro_excel(a.animal.nome), 'Raça': seguro_excel(a.animal.raca),
               'Sexo': a.animal.sexo, 'Tutor': seguro_excel(a.animal.tutor.nome_completo),
               'CPF Tutor': seguro_excel(a.animal.tutor.cpf)} for a in agendamentos]
    arquivo = io.BytesIO()
    with pd.ExcelWriter(arquivo, engine='openpyxl') as writer:
        pd.DataFrame(linhas).to_excel(writer, sheet_name='Agenda', index=False, startcol=1)
        planilha = writer.sheets['Agenda']
        margens(planilha)
        for linha in planilha.iter_rows(min_row=1, max_row=len(linhas) + 1, min_col=2, max_col=7):
            for celula in linha:
                celula.border = BORDA
    arquivo.seek(0)
    return send_file(arquivo, as_attachment=True, download_name=f'agenda_{data_str}.xlsx', mimetype=XLSX)


@app.route('/relatorios')
def relatorios():
    return render_template('relatorios.html')


if __name__ == '__main__':
    app.run(debug=False)  # no dia a dia use serve.py. Nunca ligue debug: expõe um console remoto.
