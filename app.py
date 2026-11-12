import hmac
import io
import mimetypes
import os
import re
import secrets
import tempfile
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file,
                   session, url_for)
from flask_sqlalchemy import SQLAlchemy
from openpyxl.styles import Border, Side
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import deferred, joinedload
from werkzeug.exceptions import HTTPException

import exportacao
from agenda_regras import (DIAS_CURTOS, MESES, data_extensa, dia_util, dia_util_vizinho, hoje, hora_texto,
                           ler_data, ler_mes, mes_vizinho, montar_grade, opcoes_para_animal, resumo_dia,
                           resumo_presenca, semanas_do_mes, verificar_vaga)
from config import BASE_DIR, USAR_HTTPS, segredo, url_do_banco
from seguranca import (SENHA_MAX, ErroDeCriptografia, TextoCriptografado, cifrar_bytes, decifrar_bytes, hash_senha,
                       indice_cego, normalizar, validar_chaves, verificar_senha)
from supabase_auth import (AccountAlreadyExists, AuthUnavailable, EmailConfirmationRequired,
                           InvalidCredentials, SupabaseAuth,
                           SupabaseAuthError)

INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
if os.environ.get('VERCEL'):
    INSTANCE_DIR = os.path.join(tempfile.gettempdir(), 'castramovel-instance')

app = Flask(__name__, instance_path=INSTANCE_DIR)
os.makedirs(app.instance_path, exist_ok=True)

validar_chaves()  # falha logo na partida se faltar alguma chave no .env
AUTH = SupabaseAuth()

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
ESPECIES = {'cao': 'Cão', 'gato': 'Gato'}
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
    email = db.Column(enc('usuario.email'), nullable=True)
    # 'admin' pode usar as duas interfaces (Administração e Veterinário) e trocar entre elas.
    # 'veterinario' só usa a interface Veterinário (acesso limitado). O valor antigo 'campo' equivale a 'veterinario'.
    # Contas novas entram como 'admin'; use 'veterinario' para conceder acesso limitado.
    perfil = db.Column(db.String(20), nullable=False, default='admin', server_default='admin')

    @property
    def e_admin(self):
        return self.perfil == 'admin'

    def definir_email(self, email):
        self.email = email.strip().lower()


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
    especie = db.Column(enc('animal.especie'), nullable=True)
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
    caminho = db.Column(db.String(200), nullable=False)  # id aleatório do arquivo (também protege o conteúdo cifrado)
    # Conteúdo cifrado, guardado no banco para não se perder em hospedagens sem disco permanente (Vercel).
    # Documentos antigos, sem este campo, continuam sendo lidos de instance/uploads/.
    conteudo = deferred(db.Column(db.LargeBinary, nullable=True))
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=False)


class Agendamento(db.Model):
    __tablename__ = 'agendamento'
    # Vários animais podem ocupar o mesmo horário: o limite de vagas é conferido em agenda_regras.py.
    __table_args__ = (db.Index('idx_agendamento_data', 'data'),)
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    presente = db.Column(db.Boolean, nullable=True)  # None = aguardando, True = compareceu, False = faltou
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


def email_valido(email):
    if not email or len(email) > 254 or any(c in email for c in '<>"\'(),;:\\'):
        return False
    return re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) is not None


def usuario_por_email(email):
    procurado = email.strip().casefold()
    for usuario in Usuario.query.filter(Usuario.email.isnot(None)).all():
        if hmac.compare_digest(usuario.email.casefold(), procurado):
            return usuario
    return None


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
    limites = {'nome': 100, 'telefone': 20, 'cpf': 32, 'endereco': 200, 'numero': 10}
    if not all(campos.values()):
        return campos, 'Preencha todos os campos.'
    if any(len(campos[c]) > m for c, m in limites.items()):
        return campos, 'Algum campo ultrapassa o tamanho permitido.'
    if len(so_digitos(campos['cpf'])) != 11:
        return campos, 'Informe os 11 dígitos do CPF.'
    return campos, None


def ler_animal(form):
    campos = {c: form.get(c, '').strip() for c in ('nome', 'especie', 'raca', 'sexo', 'microchip')}
    if not campos['nome'] or campos['especie'] not in ESPECIES or not campos['raca'] \
            or campos['sexo'] not in ('macho', 'femea'):
        return campos, 'Preencha nome, espécie, raça e sexo.'
    if len(campos['nome']) > 50 or len(campos['raca']) > 50 or len(campos['microchip']) > 20:
        return campos, 'Algum campo ultrapassa o tamanho permitido.'
    return campos, None


def nome_especie(especie):
    return ESPECIES.get(especie, 'Não informada')


def nome_sexo(sexo):
    return {'macho': 'Macho', 'femea': 'Fêmea'}.get(sexo, 'Não informado')


# ---------------------------------------------------------------------------
# Segurança de requisição: CSRF, login, cabeçalhos
# ---------------------------------------------------------------------------
def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


app.jinja_env.globals['csrf_token'] = csrf_token
app.jinja_env.globals['nome_especie'] = nome_especie
app.jinja_env.globals['nome_sexo'] = nome_sexo
app.jinja_env.globals['so_digitos'] = so_digitos
app.jinja_env.globals['hora_texto'] = hora_texto
app.jinja_env.globals['data_extensa'] = data_extensa
app.jinja_env.globals['DIAS_CURTOS'] = DIAS_CURTOS


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


MODO_ADMIN, MODO_VET = 'admin', 'veterinario'
NOMES_MODO = {MODO_ADMIN: 'Administração', MODO_VET: 'Veterinário'}

# Interface Veterinário: só estas rotas (e só com estes métodos). Tudo o mais é negado no servidor.
ROTAS_VET = {
    'atendimento': {'GET'}, 'marcar_presenca': {'POST'},   # atendimento do dia e presença
    'calendario': {'GET'},                                   # calendário só para ler
    'animal_perfil': {'GET'}, 'tutor_perfil': {'GET'},       # fichas só para ler
    'salvar_microchip': {'POST'},                            # única edição permitida: o microchip
    'alterar_senha': {'GET', 'POST'}, 'logout': {'POST'}, 'trocar_perfil': {'POST'},
}
# Rotas que pertencem só à interface Veterinário (a Administração não usa mais o Atendimento).
ROTAS_SO_VET = {'atendimento', 'marcar_presenca', 'salvar_microchip'}


def modo_do_usuario(usuario):
    """Interface em uso. Quem não é admin está sempre no modo Veterinário; o admin escolhe e troca pelo botão."""
    if usuario is None or not usuario.e_admin:
        return MODO_VET
    return session.get('modo') if session.get('modo') in NOMES_MODO else MODO_ADMIN


def pagina_inicial(modo):
    return url_for('atendimento' if modo == MODO_VET else 'index')


@app.before_request
def exigir_login():
    endpoint = request.endpoint
    if endpoint is None or endpoint == 'static':
        return None
    g.usuario = db.session.get(Usuario, session['usuario_id']) if session.get('usuario_id') else None
    g.modo = modo_do_usuario(g.usuario)
    if g.usuario:
        if endpoint == 'login':
            return redirect(pagina_inicial(g.modo))
        metodo = 'GET' if request.method == 'HEAD' else request.method
        if g.modo == MODO_VET:
            permitido = metodo in ROTAS_VET.get(endpoint, ())
        else:
            permitido = endpoint not in ROTAS_SO_VET
        if not permitido:
            return redirect(pagina_inicial(g.modo)) if metodo == 'GET' else abort(403)
        return None
    if endpoint != 'login':
        session.clear()
        return redirect(url_for('login', proximo=request.path if request.method == 'GET' else None))
    return None


CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")


@app.after_request
def cabecalhos(resposta):
    resposta.headers['X-Content-Type-Options'] = 'nosniff'
    # Só o arquivo do documento pode ser exibido dentro da própria página do sistema (pré-visualização de PDF).
    resposta.headers['X-Frame-Options'] = 'SAMEORIGIN' if request.endpoint == 'baixar_documento' else 'DENY'
    resposta.headers['Referrer-Policy'] = 'no-referrer'
    resposta.headers['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=()'  # câmera só para ler o código do microchip
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
    usuario = g.get('usuario')
    modo = g.get('modo', MODO_ADMIN)
    outro = MODO_VET if modo == MODO_ADMIN else MODO_ADMIN
    return {'usuario_atual': usuario, 'modo': modo, 'nome_modo': NOMES_MODO[modo],
            'pode_trocar': bool(usuario and usuario.e_admin), 'outro_modo': outro,
            'nome_outro_modo': NOMES_MODO[outro]}


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
def criar_ou_entrar_no_supabase(email, senha):
    return AUTH.sign_up_or_sign_in(email, senha)


def autenticar_usuario(email, senha):
    try:
        sessao_auth = AUTH.sign_in(email, senha)
    except InvalidCredentials:
        usuario = usuario_por_email(email)
        ok, atualizar = verificar_senha(senha, usuario.senha_hash if usuario else None)
        if not usuario or not ok:
            raise
        criar_ou_entrar_no_supabase(email, senha)
        if atualizar:
            usuario.senha_hash = hash_senha(senha)
            db.session.commit()
        return usuario

    usuario = usuario_por_email(email)
    if usuario:
        return usuario
    return criar_perfil_local(email, senha, sessao_auth)


def criar_perfil_local(email, senha, sessao_auth):
    auth_user = sessao_auth.get('user')
    if not isinstance(auth_user, dict) or not isinstance(auth_user.get('id'), str):
        raise SupabaseAuthError('Supabase Auth não retornou os dados da conta.')
    email_auth = auth_user.get('email')
    if not isinstance(email_auth, str) or email_auth.casefold() != email.casefold():
        raise SupabaseAuthError('Supabase Auth retornou um e-mail de conta inválido.')
    try:
        identificador = uuid.UUID(auth_user['id']).hex
    except ValueError as exc:
        raise SupabaseAuthError('Supabase Auth retornou um identificador inválido.') from exc

    usuario = Usuario(nome=f'supabase_{identificador}', senha_hash=hash_senha(senha))
    usuario.definir_email(email_auth)
    db.session.add(usuario)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        usuario = usuario_por_email(email_auth)
        if usuario:
            return usuario
        raise
    return usuario


def atualizar_senha_usuario(usuario, senha_atual, nova_senha):
    if not usuario.email:
        raise InvalidCredentials('Cadastre um e-mail para a conta antes de alterar a senha.')
    try:
        sessao_auth = AUTH.sign_in(usuario.email, senha_atual)
    except InvalidCredentials:
        ok, _ = verificar_senha(senha_atual, usuario.senha_hash)
        if not ok:
            raise
        criar_ou_entrar_no_supabase(usuario.email, nova_senha)
    else:
        AUTH.update_password(sessao_auth['access_token'], nova_senha)
    usuario.senha_hash = hash_senha(nova_senha)
    db.session.commit()


def atualizar_email_usuario(usuario, novo_email):
    existente = usuario_por_email(novo_email)
    if existente and existente.id != usuario.id:
        raise AccountAlreadyExists('Este e-mail já está associado a outro usuário.')
    if usuario.email and usuario.email.casefold() == novo_email.casefold():
        return
    usuario.definir_email(novo_email)
    db.session.commit()


def mensagem_de_erro_auth(erro):
    if isinstance(erro, EmailConfirmationRequired):
        return 'Confirme seu e-mail pelo link enviado pelo Supabase e tente entrar novamente.'
    if isinstance(erro, AuthUnavailable):
        return 'Não foi possível conectar à autenticação do Supabase. Tente novamente.'
    if isinstance(erro, AccountAlreadyExists):
        return 'Já existe uma conta Supabase Auth com este e-mail.'
    return 'Não foi possível concluir a autenticação. Confira a configuração do Supabase.'


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.usuario:
        return redirect(url_for('index'))
    if request.method == 'POST':
        ip = request.remote_addr
        if bloqueado(ip):
            flash('Muitas tentativas. Aguarde alguns minutos e tente de novo.', 'error')
            return render_template('login.html'), 429
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        if not email_valido(email):
            flash('Informe um e-mail válido.', 'error')
            return render_template('login.html')
        if len(senha) > SENHA_MAX:
            registrar_falha(ip)
            flash('E-mail ou senha incorretos.', 'error')
            return render_template('login.html')
        try:
            usuario = autenticar_usuario(email, senha)
        except InvalidCredentials:
            registrar_falha(ip)
            flash('E-mail ou senha incorretos.', 'error')
            return render_template('login.html')
        except SupabaseAuthError as exc:
            app.logger.warning('Autenticação Supabase falhou: %s', exc)
            flash(mensagem_de_erro_auth(exc), 'error')
            status = 503 if isinstance(exc, AuthUnavailable) else 200
            return render_template('login.html'), status
        FALHAS.pop(ip, None)
        session.clear()
        session['usuario_id'] = usuario.id
        session.permanent = True
        return redirect(destino_seguro(request.args.get('proximo')))
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/trocar_perfil', methods=['POST'])
def trocar_perfil():
    """Alterna entre Administração e Veterinário. Só contas admin podem; o veterinário puro não sobe de nível."""
    novo = request.form.get('modo')
    if novo not in NOMES_MODO or not g.usuario.e_admin:
        abort(403)
    session['modo'] = novo
    return redirect(pagina_inicial(novo))


@app.route('/alterar_senha', methods=['GET', 'POST'])
def alterar_senha():
    if request.method == 'POST':
        atual = request.form.get('atual', '')
        nova = request.form.get('senha', '')
        erro = validar_senha(nova, request.form.get('confirmacao', ''))
        if erro:
            flash(erro, 'error')
        else:
            try:
                atualizar_senha_usuario(g.usuario, atual, nova)
            except InvalidCredentials:
                flash('A senha atual está incorreta.', 'error')
            except SupabaseAuthError as exc:
                app.logger.warning('Alteração de senha Supabase falhou: %s', exc)
                flash(mensagem_de_erro_auth(exc), 'error')
            else:
                flash('Senha alterada.', 'success')
                return redirect(pagina_inicial(g.modo))
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
        cifrado = cifrar_bytes(conteudo, f'documento.arquivo:{guardado}')
        db.session.add(Documento(nome_arquivo=original, caminho=guardado, conteudo=cifrado, tutor_id=tutor.id))
    db.session.commit()
    if recusados:
        flash(f'{recusados} arquivo(s) não enviado(s). Use PDF, imagem, Word, Excel ou texto.', 'error')


def extensao_do_documento(doc):
    nome = doc.nome_arquivo
    return nome.rsplit('.', 1)[-1].lower() if '.' in nome else ''


def ler_conteudo_documento(doc):
    """Conteúdo já descriptografado, ou None se o arquivo não está mais disponível."""
    guardado = os.path.basename(doc.caminho.replace('\\', '/'))
    aad = f'documento.arquivo:{guardado}'
    try:
        if doc.conteudo is not None:
            return decifrar_bytes(bytes(doc.conteudo), aad)
        caminho = os.path.join(app.config['UPLOAD_FOLDER'], guardado)  # documentos enviados antes desta versão
        if os.path.isfile(caminho):
            with open(caminho, 'rb') as f:
                return decifrar_bytes(f.read(), aad)
    except ErroDeCriptografia:
        app.logger.warning('Documento %s não pôde ser descriptografado', doc.id)
    return None


@app.route('/documento/<int:id>')
def baixar_documento(id):
    """O arquivo em si. Com ?baixar=1 força o download; PDF e imagem abrem no navegador."""
    doc = db.get_or_404(Documento, id)
    conteudo = ler_conteudo_documento(doc)
    if conteudo is None:
        abort(404)
    extensao = extensao_do_documento(doc)
    mostrar = extensao in EXIBIR_NO_NAVEGADOR and not request.args.get('baixar')
    return send_file(io.BytesIO(conteudo), mimetype=mimetypes.guess_type(doc.nome_arquivo)[0] or 'application/octet-stream',
                     as_attachment=not mostrar, download_name=doc.nome_arquivo)


@app.route('/documento/<int:id>/ver')
def ver_documento(id):
    """Página de visualização dentro do sistema, com botões de abrir em nova aba e baixar."""
    doc = db.get_or_404(Documento, id)
    extensao = extensao_do_documento(doc)
    disponivel = ler_conteudo_documento(doc) is not None
    tipo = 'pdf' if extensao == 'pdf' else 'imagem' if extensao in EXIBIR_NO_NAVEGADOR else 'outro'
    return render_template('documento_ver.html', doc=doc, tutor=doc.tutor, tipo=tipo, disponivel=disponivel)


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


LIMITE_LISTA = 12  # quantos tutores aparecem de uma vez nas listas de escolha


def contagem_animais():
    return dict(db.session.query(Animal.tutor_id, db.func.count(Animal.id)).group_by(Animal.tutor_id).all())


def resumir_tutores(tutores):
    """Dados mostrados em cada tutor das listas de escolha (nome e uma linha de detalhes)."""
    contagem = contagem_animais()
    itens = []
    for tutor in tutores:
        n = contagem.get(tutor.id, 0)
        partes = [tutor.telefone]
        digitos = so_digitos(tutor.cpf)
        if len(digitos) == 11:
            partes.append(f'CPF ***.***.***-{digitos[-2:]}')
        partes.append('sem animais' if n == 0 else '1 animal' if n == 1 else f'{n} animais')
        itens.append({'id': tutor.id, 'nome': tutor.nome_completo, 'detalhe': ' · '.join(partes)})
    return itens


def tutores_para_lista(busca):
    encontrados = buscar_tutores(busca) if busca else todos_tutores()
    return resumir_tutores(encontrados[:LIMITE_LISTA]), len(encontrados)


def tutor_escolhido():
    """Tutor indicado em ?tutor_id= (ou no formulário), ou None."""
    try:
        return db.session.get(Tutor, int(request.values.get('tutor_id', '')))
    except ValueError:
        return None


def agendamentos_do_dia(dia):
    return (Agendamento.query.options(joinedload(Agendamento.animal).joinedload(Animal.tutor))
            .filter_by(data=dia).order_by(Agendamento.hora, Agendamento.id).all())


def bloquear_dia(dia):
    """Faz agendamentos do mesmo dia esperarem a vez (PostgreSQL), para duas pessoas
    não passarem do limite de vagas ao clicar ao mesmo tempo. Liberado no commit/rollback."""
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(db.text('select pg_advisory_xact_lock(:chave)'), {'chave': dia.toordinal()})


def voltar_para():
    return request.full_path.rstrip('?')


@app.context_processor
def contexto_agenda():
    return {'hoje': hoje()}


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    dia = hoje()  # só o dia de hoje; os demais ficam na aba Calendário
    grade = montar_grade(agendamentos_do_dia(dia))
    proximo = (db.session.query(db.func.min(Agendamento.data)).filter(Agendamento.data > dia).scalar())
    return render_template('index.html', dia=dia, grade=grade, util=dia_util(dia), proximo=proximo,
                           total_tutores=Tutor.query.count(), total_animais=Animal.query.count())


@app.route('/calendario')
def calendario():
    hj = hoje()
    ano, mes = ler_mes(request.args.get('mes'), hj)
    semanas = semanas_do_mes(ano, mes)
    primeiro, ultimo = semanas[0][0], semanas[-1][-1]
    dia = ler_data(request.args.get('dia'))
    if dia is None or not primeiro <= dia <= ultimo:
        dia = hj if (hj.year, hj.month) == (ano, mes) else date(ano, mes, 1)
    agendamentos = (Agendamento.query.options(joinedload(Agendamento.animal).joinedload(Animal.tutor))
                    .filter(Agendamento.data.between(primeiro, ultimo))
                    .order_by(Agendamento.data, Agendamento.hora, Agendamento.id).all())
    por_dia = defaultdict(list)
    for ag in agendamentos:
        por_dia[ag.data].append(ag)
    resumos = {d: resumo_dia(lista) for d, lista in por_dia.items()}
    anterior, seguinte = mes_vizinho(ano, mes, -1), mes_vizinho(ano, mes, 1)
    return render_template('calendario.html', ano=ano, mes=mes, nome_mes=MESES[mes - 1].capitalize(),
                           semanas=semanas, resumos=resumos, dia=dia, util=dia_util(dia),
                           grade=montar_grade(por_dia.get(dia, [])), voltar=voltar_para(),
                           mes_anterior=f'{anterior[0]}-{anterior[1]:02d}',
                           mes_seguinte=f'{seguinte[0]}-{seguinte[1]:02d}',
                           mes_atual=f'{hj.year}-{hj.month:02d}', editar=g.modo == MODO_ADMIN)


@app.route('/api/tutores')
def api_tutores():
    """Busca de tutores enquanto a pessoa digita (usada pelas telas de animal e agendamento)."""
    itens, total = tutores_para_lista(request.args.get('q', '').strip()[:100])
    return jsonify(tutores=itens, total=total)


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
    tutor = tutor_escolhido()
    busca = request.args.get('q', '').strip()
    if tutor is None:  # passo 1: escolher o tutor
        itens, total = tutores_para_lista(busca)
        return render_template('cadastrar_animal.html', tutor=None, busca=busca, itens=itens, total=total,
                               form={}, limite=LIMITE_LISTA)
    if request.method == 'POST':
        dados, erro = ler_animal(request.form)
        if not erro:
            animal = Animal(nome=dados['nome'], especie=dados['especie'], raca=dados['raca'],
                            sexo=dados['sexo'], tutor_id=tutor.id)
            animal.definir_microchip(dados['microchip'])
            db.session.add(animal)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                erro = 'Já existe um animal com esse microchip.'
        if erro:
            flash(erro, 'error')
            return render_template('cadastrar_animal.html', tutor=tutor, form=request.form)
        flash(f'{animal.nome} cadastrado(a) com sucesso!', 'success')
        return redirect(url_for('tutor_perfil', id=tutor.id))
    return render_template('cadastrar_animal.html', tutor=tutor, form={})


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
    if g.modo == MODO_VET:  # veterinário: só leitura, sem documentos anexados
        return render_template('tutor_vet.html', tutor=tutor)
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
    if not erro and (dados['especie'], dados['sexo']) != (animal.especie, animal.sexo):
        futuro = Agendamento.query.filter(Agendamento.animal_id == animal.id, Agendamento.data >= hoje()).first()
        if futuro:
            erro = ('Este animal tem agendamento a partir de hoje. Cancele o agendamento antes de mudar a espécie '
                    'ou o sexo, pois cada horário atende apenas algumas categorias.')
    if not erro:
        animal.nome, animal.especie = dados['nome'], dados['especie']
        animal.raca, animal.sexo = dados['raca'], dados['sexo']
        animal.definir_microchip(dados['microchip'])
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            erro = 'Já existe outro animal com esse microchip.'
    flash(erro or 'Animal atualizado!', 'error' if erro else 'success')


def historico_do_animal(animal):
    return (Agendamento.query.filter_by(animal_id=animal.id)
            .order_by(Agendamento.data.desc(), Agendamento.hora.desc()).all())


@app.route('/editar_animal/<int:id>', methods=['GET', 'POST'])
def editar_animal(id):
    animal = db.get_or_404(Animal, id)
    if request.method == 'POST':
        salvar_animal(animal)
    return render_template('editar_animal.html', animal=animal, historico=historico_do_animal(animal),
                           voltar=voltar_para())


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
    if g.modo == MODO_VET:  # veterinário: só leitura, exceto o formulário do microchip
        return render_template('animal_vet.html', animal=animal, historico=historico_do_animal(animal))
    if request.method == 'POST':
        salvar_animal(animal)
    return render_template('animal_perfil.html', animal=animal, historico=historico_do_animal(animal),
                           voltar=voltar_para())


@app.route('/animal/<int:id>/microchip', methods=['POST'])
def salvar_microchip(id):
    """Único dado do animal que o veterinário pode alterar: adicionar, trocar ou apagar o microchip."""
    animal = db.get_or_404(Animal, id)
    valor = request.form.get('microchip', '').strip()
    if len(valor) > 20:
        flash('O microchip ultrapassa o tamanho permitido.', 'error')
    else:
        animal.definir_microchip(valor)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Já existe outro animal com esse microchip.', 'error')
        else:
            flash('Microchip salvo.' if animal.microchip else 'Microchip removido.', 'success')
    return redirect(url_for('animal_perfil', id=animal.id))


@app.route('/agendamentos')
def agendamentos():
    """Passo a passo: tutor, animal, data e horário. Tudo por GET; só a confirmação é POST (/agendar)."""
    hj = hoje()
    data = ler_data(request.args.get('data'))
    hora_escolhida = request.args.get('hora', '')
    extras = {k: request.args[k] for k in ('data', 'hora') if request.args.get(k)}
    tutor = tutor_escolhido()
    if tutor is None:  # passo 1
        busca = request.args.get('q', '').strip()
        itens, total = tutores_para_lista(busca)
        return render_template('agendamentos.html', tutor=None, busca=busca, itens=itens, total=total,
                               extras=extras, limite=LIMITE_LISTA)

    animais = sorted(tutor.animais, key=lambda a: normalizar(a.nome))
    animal = next((a for a in animais if str(a.id) == request.args.get('animal_id', '')), None)
    if animal is None and len(animais) == 1:
        animal = animais[0]
    opcoes, erro_data = [], None
    if animal is not None and data is not None:
        if not dia_util(data):
            erro_data = 'Atendemos apenas de segunda a sexta. Escolha outra data.'
        elif data < hj:
            erro_data = 'Essa data já passou. Escolha hoje ou uma data futura (para ver dias anteriores use o Calendário).'
        else:
            opcoes = opcoes_para_animal(montar_grade(agendamentos_do_dia(data)), animal.especie, animal.sexo)
    return render_template('agendamentos.html', tutor=tutor, animais=animais, animal=animal, data=data,
                           hora_escolhida=hora_escolhida, opcoes=opcoes, erro_data=erro_data, extras=extras,
                           animal_sem_dados=animal is not None and (animal.especie not in ESPECIES
                                                                    or animal.sexo not in ('macho', 'femea')))


@app.route('/agendar', methods=['POST'])
def agendar():
    try:
        data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
        hora = datetime.strptime(request.form['hora'], '%H:%M').time()
    except (KeyError, ValueError):
        flash('Escolha a data e o horário.', 'error')
        return redirect(url_for('agendamentos'))
    animal = db.get_or_404(Animal, inteiro(request.form.get('animal_id')))
    voltar = url_for('agendamentos', tutor_id=animal.tutor_id, animal_id=animal.id, data=data.isoformat())
    erro = None
    if not dia_util(data):
        erro = 'Agendamentos apenas de segunda a sexta.'
    elif data < hoje():
        erro = 'Escolha hoje ou uma data futura.'
    else:
        bloquear_dia(data)  # a conferência de vagas e a gravação acontecem sem outra pessoa no meio
        _, erro = verificar_vaga(hora, animal.especie, animal.sexo, agendamentos_do_dia(data))
        if not erro:
            ja = (Agendamento.query.filter(Agendamento.animal_id == animal.id, Agendamento.data >= hoje())
                  .order_by(Agendamento.data, Agendamento.hora).first())
            if ja:
                erro = (f'{animal.nome} já está agendado(a) para {ja.data.strftime("%d/%m/%Y")} às '
                        f'{hora_texto(ja.hora)}. Cancele esse agendamento antes de marcar outro.')
    if erro:
        db.session.rollback()
        flash(erro, 'error')
        return redirect(voltar)
    db.session.add(Agendamento(data=data, hora=hora, animal_id=animal.id))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        app.logger.exception('Falha ao gravar agendamento (o banco foi atualizado com o supabase_schema.sql?)')
        flash('Não foi possível salvar o agendamento. Tente novamente; se continuar, avise o responsável pelo sistema.',
              'error')
        return redirect(voltar)
    flash(f'{animal.nome} agendado(a) para {data.strftime("%d/%m/%Y")} às {hora_texto(hora)}.', 'success')
    return redirect(url_for('calendario', mes=f'{data.year}-{data.month:02d}', dia=data.isoformat()))


@app.route('/agendamentos/<int:id>/cancelar', methods=['POST'])
def cancelar_agendamento(id):
    ag = db.get_or_404(Agendamento, id)
    destino = destino_seguro(request.form.get('voltar'))
    if ag.data < hoje():
        flash('Agendamentos de dias anteriores ficam guardados como registro e não podem ser cancelados.', 'error')
    else:
        db.session.delete(ag)
        db.session.commit()
        flash('Agendamento cancelado. A vaga está livre novamente.', 'success')
    return redirect(destino)


# ---------------------------------------------------------------------------
# Atendimento (interface Veterinário): quem está agendado no dia e marcação de presença
# ---------------------------------------------------------------------------
@app.route('/atendimento')
def atendimento():
    hj = hoje()
    dia = ler_data(request.args.get('data')) or hj
    lista = agendamentos_do_dia(dia)
    return render_template('atendimento.html', dia=dia, grade=montar_grade(lista), util=dia_util(dia),
                           resumo=resumo_presenca(lista), pode_marcar=dia <= hj,
                           anterior=dia_util_vizinho(dia, -1), seguinte=dia_util_vizinho(dia, 1),
                           voltar=url_for('atendimento', data=dia.isoformat()))


@app.route('/atendimento/<int:id>/presenca', methods=['POST'])
def marcar_presenca(id):
    ag = db.get_or_404(Agendamento, id)
    valor = request.form.get('valor')
    if valor not in ('presente', 'faltou', 'limpar'):
        abort(400)
    destino = destino_seguro(request.form.get('voltar')) + f'#ag-{ag.id}'
    if ag.data > hoje():
        flash('A presença só pode ser marcada a partir do dia do atendimento.', 'error')
    else:
        ag.presente = {'presente': True, 'faltou': False, 'limpar': None}[valor]
        db.session.commit()
    return redirect(destino)


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

    colunas = ['Data', 'Hora', 'Animal', 'Espécie', 'Raça', 'Sexo', 'Tutor', 'CPF Tutor']
    arquivo = io.BytesIO()
    with pd.ExcelWriter(arquivo, engine='openpyxl') as writer:
        for dia in sorted(por_dia):
            linhas = [dict.fromkeys(colunas, ''), dict(zip(colunas, colunas))]
            linhas[0]['Data'] = dia.strftime('%d/%m/%Y')
            for a in por_dia[dia]:
                linhas.append({'Data': dia.strftime('%d/%m/%Y'), 'Hora': str(a.hora),
                               'Animal': seguro_excel(a.animal.nome), 'Espécie': nome_especie(a.animal.especie),
                               'Raça': seguro_excel(a.animal.raca),
                               'Sexo': a.animal.sexo, 'Tutor': seguro_excel(a.animal.tutor.nome_completo),
                               'CPF Tutor': seguro_excel(a.animal.tutor.cpf)})
            nome_aba = dia.strftime('%d-%m')
            pd.DataFrame(linhas).to_excel(writer, sheet_name=nome_aba, index=False)
            planilha = writer.sheets[nome_aba]
            for linha in planilha.iter_rows(min_row=1, max_row=len(linhas), min_col=1, max_col=8):
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
    linhas = [{'Hora': a.hora, 'Animal': seguro_excel(a.animal.nome),
               'Espécie': nome_especie(a.animal.especie), 'Raça': seguro_excel(a.animal.raca),
               'Sexo': a.animal.sexo, 'Tutor': seguro_excel(a.animal.tutor.nome_completo),
               'CPF Tutor': seguro_excel(a.animal.tutor.cpf)} for a in agendamentos]
    arquivo = io.BytesIO()
    with pd.ExcelWriter(arquivo, engine='openpyxl') as writer:
        pd.DataFrame(linhas).to_excel(writer, sheet_name='Agenda', index=False, startcol=1)
        planilha = writer.sheets['Agenda']
        margens(planilha)
        for linha in planilha.iter_rows(min_row=1, max_row=len(linhas) + 1, min_col=2, max_col=8):
            for celula in linha:
                celula.border = BORDA
    arquivo.seek(0)
    return send_file(arquivo, as_attachment=True, download_name=f'agenda_{data_str}.xlsx', mimetype=XLSX)


@app.route('/gerar_csv_animalltag')
def gerar_csv_animalltag():
    """CSV com tutor e microchip dos animais agendados no período, para enviar ao AnimallTAG."""
    de, ate = ler_data(request.args.get('de')), ler_data(request.args.get('ate'))
    if de is None or ate is None or ate < de or (ate - de).days > 366:
        flash('Informe um período válido (data inicial e final, de até um ano).', 'error')
        return redirect(url_for('relatorios'))
    so_presentes = request.args.get('presentes') == '1'
    agendamentos = (Agendamento.query.options(joinedload(Agendamento.animal).joinedload(Animal.tutor))
                    .filter(Agendamento.data.between(de, ate))
                    .order_by(Agendamento.data, Agendamento.hora, Agendamento.id).all())
    linhas, vistos = [], set()
    for ag in agendamentos:
        animal = ag.animal
        if (so_presentes and ag.presente is not True) or animal.id in vistos or not animal.microchip:
            continue
        vistos.add(animal.id)
        tutor = animal.tutor
        linhas.append({'microchip': animal.microchip, 'animal': animal.nome, 'especie': nome_especie(animal.especie),
                       'raca': animal.raca, 'sexo': nome_sexo(animal.sexo), 'tutor': tutor.nome_completo,
                       'cpf': tutor.cpf, 'telefone': tutor.telefone, 'endereco': tutor.endereco,
                       'numero': tutor.numero, 'data': ag.data.isoformat()})
    if not linhas:
        flash('Nenhum animal com microchip cadastrado nesse período'
              + (' e com presença marcada.' if so_presentes else '.'), 'error')
        return redirect(url_for('relatorios'))
    return send_file(io.BytesIO(exportacao.montar_csv(linhas)), as_attachment=True,
                     download_name=f'animalltag_{de.isoformat()}_{ate.isoformat()}.csv', mimetype='text/csv')


@app.route('/relatorios')
def relatorios():
    return render_template('relatorios.html', layout_confirmado=exportacao.LAYOUT_CONFIRMADO)


if __name__ == '__main__':
    app.run(debug=False)  # no dia a dia use serve.py. Nunca ligue debug: expõe um console remoto.
