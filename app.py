import io
import os
import secrets
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
from flask import (Flask, flash, g, redirect, render_template, request, send_file,
                   send_from_directory, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from openpyxl.styles import Border, Side
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')

app = Flask(__name__, instance_path=INSTANCE_DIR)
os.makedirs(app.instance_path, exist_ok=True)


def carregar_chave():
    """Chave de sessão: variável de ambiente ou arquivo gerado na primeira execução."""
    chave = os.environ.get('CASTRAMOVEL_SECRET_KEY')
    if chave:
        return chave
    caminho = os.path.join(app.instance_path, 'secret.key')
    if not os.path.exists(caminho):
        with open(caminho, 'w') as f:
            f.write(secrets.token_hex(32))
    with open(caminho) as f:
        return f.read().strip()


app.config['SECRET_KEY'] = carregar_chave()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///castramovel.db'
app.config['UPLOAD_FOLDER'] = os.path.join(app.instance_path, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

db = SQLAlchemy(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

EXTENSOES = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'doc', 'docx', 'odt', 'xls', 'xlsx', 'txt'}
EXIBIR_NO_NAVEGADOR = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'}
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


# Models
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)

class Tutor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_completo = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    cpf = db.Column(db.String(14), unique=True, nullable=False)
    endereco = db.Column(db.String(200), nullable=False)
    numero = db.Column(db.String(10), nullable=False)
    documentos = db.relationship('Documento', backref='tutor', lazy=True)
    animais = db.relationship('Animal', backref='tutor', lazy=True)

class Animal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)
    raca = db.Column(db.String(50), nullable=False)
    sexo = db.Column(db.String(10), nullable=False)  # macho ou femea
    microchip = db.Column(db.String(20), unique=True, nullable=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=False)

class Documento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_arquivo = db.Column(db.String(100), nullable=False)  # nome original, usado na tela
    caminho = db.Column(db.String(200), nullable=False)       # nome guardado em uploads/
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=False)

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    animal = db.relationship('Animal', backref='agendamentos')

with app.app_context():
    db.create_all()


# Autenticação
FALHAS = {}  # ip -> [falhas seguidas, bloqueado até]
MAX_FALHAS = 5
BLOQUEIO = timedelta(minutes=5)


def bloqueado(ip):
    registro = FALHAS.get(ip)
    return bool(registro and registro[1] and registro[1] > datetime.now())


def registrar_falha(ip):
    registro = FALHAS.setdefault(ip, [0, None])
    registro[0] += 1
    if registro[0] >= MAX_FALHAS:
        FALHAS[ip] = [0, datetime.now() + BLOQUEIO]


def validar_senha(senha, confirmacao):
    if len(senha) < 8:
        return 'A senha deve ter pelo menos 8 caracteres.'
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
    g.usuario = db.session.get(Usuario, session['usuario_id']) if 'usuario_id' in session else None
    if Usuario.query.count() == 0:
        return None if endpoint == 'primeiro_acesso' else redirect(url_for('primeiro_acesso'))
    if endpoint == 'primeiro_acesso':
        return redirect(url_for('login'))
    if g.usuario is None and endpoint != 'login':
        session.clear()
        return redirect(url_for('login', proximo=request.path if request.method == 'GET' else None))
    return None


@app.after_request
def cabecalhos(resposta):
    resposta.headers['X-Content-Type-Options'] = 'nosniff'
    if request.endpoint != 'static':
        resposta.headers['Cache-Control'] = 'no-store'
    return resposta


@app.context_processor
def contexto():
    return {'usuario_atual': g.get('usuario')}


@app.route('/primeiro_acesso', methods=['GET', 'POST'])
def primeiro_acesso():
    if request.method == 'POST':
        nome = request.form.get('usuario', '').strip().lower()
        erro = None if nome else 'Informe um nome de usuário.'
        erro = erro or validar_senha(request.form.get('senha', ''), request.form.get('confirmacao', ''))
        if erro:
            flash(erro, 'error')
        else:
            usuario = Usuario(nome=nome, senha_hash=generate_password_hash(request.form['senha']))
            db.session.add(usuario)
            db.session.commit()
            session.clear()
            session['usuario_id'] = usuario.id
            session.permanent = True
            flash('Usuário criado.', 'success')
            return redirect(url_for('index'))
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
        usuario = Usuario.query.filter_by(nome=nome).first()
        if usuario and check_password_hash(usuario.senha_hash, request.form.get('senha', '')):
            FALHAS.pop(ip, None)
            session.clear()
            session['usuario_id'] = usuario.id
            session.permanent = True
            return redirect(destino_seguro(request.args.get('proximo')))
        registrar_falha(ip)
        flash('Usuário ou senha incorretos.', 'error')
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/alterar_senha', methods=['GET', 'POST'])
def alterar_senha():
    if request.method == 'POST':
        if not check_password_hash(g.usuario.senha_hash, request.form.get('atual', '')):
            flash('A senha atual está incorreta.', 'error')
        else:
            erro = validar_senha(request.form.get('senha', ''), request.form.get('confirmacao', ''))
            if erro:
                flash(erro, 'error')
            else:
                g.usuario.senha_hash = generate_password_hash(request.form['senha'])
                db.session.commit()
                flash('Senha alterada.', 'success')
                return redirect(url_for('index'))
    return render_template('alterar_senha.html')


# Documentos
def salvar_documentos(arquivos, tutor):
    recusados = 0
    for arquivo in arquivos:
        if not arquivo.filename:
            continue
        original = os.path.basename(arquivo.filename.replace('\\', '/'))[:100]
        extensao = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
        if extensao not in EXTENSOES:
            recusados += 1
            continue
        guardado = f'{uuid.uuid4().hex}.{extensao}'
        arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], guardado))
        db.session.add(Documento(nome_arquivo=original, caminho=guardado, tutor_id=tutor.id))
    db.session.commit()
    if recusados:
        flash(f'{recusados} arquivo(s) não enviado(s). Use PDF, imagem, Word, Excel ou texto.', 'error')


@app.route('/documento/<int:id>')
def baixar_documento(id):
    doc = Documento.query.get_or_404(id)
    guardado = os.path.basename(doc.caminho.replace('\\', '/'))  # aceita registros antigos
    extensao = doc.nome_arquivo.rsplit('.', 1)[-1].lower() if '.' in doc.nome_arquivo else ''
    return send_from_directory(app.config['UPLOAD_FOLDER'], guardado,
                               as_attachment=extensao not in EXIBIR_NO_NAVEGADOR,
                               download_name=doc.nome_arquivo)


# Routes
@app.route('/')
def index():
    proximos = (Agendamento.query.filter(Agendamento.data >= date.today())
                .order_by(Agendamento.data, Agendamento.hora).limit(10).all())
    return render_template('index.html', proximos=proximos,
                           total_tutores=Tutor.query.count(), total_animais=Animal.query.count())

@app.route('/cadastrar_tutor', methods=['GET', 'POST'])
def cadastrar_tutor():
    if request.method == 'POST':
        tutor = Tutor(nome_completo=request.form['nome'], telefone=request.form['telefone'],
                      cpf=request.form['cpf'], endereco=request.form['endereco'],
                      numero=request.form['numero'])
        db.session.add(tutor)
        db.session.commit()
        salvar_documentos(request.files.getlist('documentos'), tutor)
        flash('Tutor cadastrado com sucesso!', 'success')
        return redirect(url_for('index'))
    return render_template('cadastrar_tutor.html')

@app.route('/cadastrar_animal', methods=['GET', 'POST'])
def cadastrar_animal():
    search = request.args.get('search', '')
    tutores = Tutor.query.filter(Tutor.nome_completo.contains(search)).all() if search else Tutor.query.all()
    if request.method == 'POST':
        animal = Animal(nome=request.form['nome'], raca=request.form['raca'], sexo=request.form['sexo'],
                        microchip=request.form.get('microchip') or None, tutor_id=request.form['tutor_id'])
        db.session.add(animal)
        db.session.commit()
        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('index'))
    return render_template('cadastrar_animal.html', tutores=tutores, search=search)

@app.route('/procurar_tutor', methods=['GET', 'POST'])
def procurar_tutor():
    tutores = []
    busca = ''
    if request.method == 'POST':
        busca = request.form['busca']
        tutores = Tutor.query.filter(
            (Tutor.nome_completo.contains(busca)) | (Tutor.cpf.contains(busca))
        ).all()
    return render_template('procurar_tutor.html', tutores=tutores, busca=busca)

@app.route('/tutor/<int:id>', methods=['GET', 'POST'])
def tutor_perfil(id):
    tutor = Tutor.query.get_or_404(id)
    if request.method == 'POST':
        tutor.nome_completo = request.form['nome']
        tutor.telefone = request.form['telefone']
        tutor.cpf = request.form['cpf']
        tutor.endereco = request.form['endereco']
        tutor.numero = request.form['numero']
        db.session.commit()
        salvar_documentos(request.files.getlist('documentos'), tutor)
        flash('Perfil atualizado!', 'success')
    return render_template('tutor_perfil.html', tutor=tutor)

@app.route('/editar_animal/<int:id>', methods=['GET', 'POST'])
def editar_animal(id):
    animal = Animal.query.get_or_404(id)
    if request.method == 'POST':
        animal.nome = request.form['nome']
        animal.raca = request.form['raca']
        animal.sexo = request.form['sexo']
        animal.microchip = request.form.get('microchip') or None
        db.session.commit()
        flash('Animal atualizado!', 'success')
    return render_template('editar_animal.html', animal=animal)

@app.route('/procurar_animal', methods=['GET', 'POST'])
def procurar_animal():
    animais = []
    busca = ''
    if request.method == 'POST':
        busca = request.form['busca']
        animais = Animal.query.filter(
            (Animal.nome.contains(busca)) | (Animal.microchip.contains(busca))
        ).all()
    return render_template('procurar_animal.html', animais=animais, busca=busca)

@app.route('/animal/<int:id>', methods=['GET', 'POST'])
def animal_perfil(id):
    animal = Animal.query.get_or_404(id)
    if request.method == 'POST':
        animal.nome = request.form['nome']
        animal.raca = request.form['raca']
        animal.sexo = request.form['sexo']
        animal.microchip = request.form.get('microchip') or None
        db.session.commit()
        flash('Animal atualizado!', 'success')
    return render_template('animal_perfil.html', animal=animal)

@app.route('/agendamentos', methods=['GET', 'POST'])
def agendamentos():
    tutores = Tutor.query.all()
    selected_tutor = None
    animais = []
    if request.method == 'POST':
        tutor_id = request.form.get('tutor_id')
        if tutor_id:
            selected_tutor = Tutor.query.get(tutor_id)
            animais = selected_tutor.animais
    return render_template('agendamentos.html', tutores=tutores, selected_tutor=selected_tutor, animais=animais)

@app.route('/agendar', methods=['POST'])
def agendar():
    data = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
    hora = datetime.strptime(request.form['hora'], '%H:%M').time()
    animal_id = request.form['animal_id']
    if Agendamento.query.filter_by(data=data, hora=hora).first():
        flash('Horário já ocupado!', 'error')
        return redirect(url_for('agendamentos'))
    db.session.add(Agendamento(data=data, hora=hora, animal_id=animal_id))
    db.session.commit()
    flash('Agendamento realizado!', 'success')
    return redirect(url_for('agendamentos'))


# Relatórios (gerados em memória, sem gravar arquivos com dados pessoais no disco)
BORDA = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))


def margens(planilha):
    for lado in ('left', 'right', 'top', 'bottom'):
        setattr(planilha.page_margins, lado, 0.5)
    planilha.page_margins.header = 0.3
    planilha.page_margins.footer = 0.3


@app.route('/gerar_excel_mes')
def gerar_excel_mes():
    ano = int(request.args.get('ano', 2026))
    mes = int(request.args.get('mes', 4))
    inicio = datetime(ano, mes, 1)
    fim = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    agendamentos = (Agendamento.query.filter(Agendamento.data.between(inicio.date(), fim.date()))
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
                linhas.append({'Data': dia.strftime('%d/%m/%Y'), 'Hora': str(a.hora), 'Animal': a.animal.nome,
                               'Raça': a.animal.raca, 'Sexo': a.animal.sexo,
                               'Tutor': a.animal.tutor.nome_completo, 'CPF Tutor': a.animal.tutor.cpf})
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
    dia = datetime.strptime(data_str, '%Y-%m-%d').date()
    agendamentos = Agendamento.query.filter_by(data=dia).order_by(Agendamento.hora).all()
    linhas = [{'Hora': a.hora, 'Animal': a.animal.nome, 'Raça': a.animal.raca, 'Sexo': a.animal.sexo,
               'Tutor': a.animal.tutor.nome_completo, 'CPF Tutor': a.animal.tutor.cpf} for a in agendamentos]
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
    app.run(debug=True)  # só para desenvolvimento local; no dia a dia use serve.py
