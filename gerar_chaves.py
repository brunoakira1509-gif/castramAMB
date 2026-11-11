"""Cria o arquivo .env com chaves aleatórias. Nunca sobrescreve um .env existente.

  python gerar_chaves.py
"""
import base64
import os
import secrets
import sys

CAMINHO = os.path.join(os.path.abspath(os.path.dirname(__file__)), '.env')


def chave():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


MODELO = """# Segredos do CastraMóvel. NÃO envie este arquivo para o git, e-mail ou chat.
# Faça uma cópia de segurança (gerenciador de senhas / pen drive guardado).
# Se CASTRAMOVEL_DATA_KEY for perdida, os dados do banco NÃO podem ser recuperados.

# Cole aqui a string de conexão do Supabase (Connect > Session pooler), com a senha do banco.
DATABASE_URL=COLE_A_STRING_DE_CONEXAO_AQUI

CASTRAMOVEL_SECRET_KEY={secret}
CASTRAMOVEL_DATA_KEY={dados}
CASTRAMOVEL_INDEX_KEY={indice}
CASTRAMOVEL_PEPPER={pepper}

# E-mail que envia o código de verificação do login (SMTP).
# Gmail: SMTP_HOST=smtp.gmail.com, porta 587, SMTP_USER = seu e-mail, SMTP_PASSWORD = "senha de app"
# (Conta Google > Segurança > Verificação em duas etapas > Senhas de app). Não use a senha normal.
SMTP_HOST=COLE_O_SERVIDOR_SMTP
SMTP_PORT=587
SMTP_USER=COLE_O_USUARIO_SMTP
SMTP_PASSWORD=COLE_A_SENHA_SMTP
SMTP_FROM=CastraMóvel <COLE_O_EMAIL_REMETENTE>

# Coloque 1 somente se o sistema for acessado por HTTPS.
CASTRAMOVEL_HTTPS=0
"""

if os.path.exists(CAMINHO):
    sys.exit('Já existe um .env. Não vou sobrescrever (trocar a DATA_KEY tornaria os dados ilegíveis).')

fd = os.open(CAMINHO, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as f:
    f.write(MODELO.format(secret=secrets.token_hex(32), dados=chave(), indice=chave(), pepper=chave()))
print('Arquivo .env criado.')
print('1) Abra o .env e cole a DATABASE_URL do Supabase.')
print('2) Preencha também os dados de SMTP (e-mail que envia o código de login).')
print('3) Guarde uma cópia do .env em local seguro.')
