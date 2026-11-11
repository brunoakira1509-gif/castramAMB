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

# URL e chave publicável do projeto Supabase (Settings > API Keys).
SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=

# String de conexão PostgreSQL do Supabase (Connect > Direct > Transaction pooler).
DATABASE_URL=COLE_A_STRING_DE_CONEXAO_AQUI

CASTRAMOVEL_SECRET_KEY={secret}
CASTRAMOVEL_DATA_KEY={dados}
CASTRAMOVEL_INDEX_KEY={indice}
CASTRAMOVEL_PEPPER={pepper}

# Coloque 1 somente se o sistema for acessado por HTTPS.
CASTRAMOVEL_HTTPS=0
"""

if os.path.exists(CAMINHO):
    sys.exit('Já existe um .env. Não vou sobrescrever (trocar a DATA_KEY tornaria os dados ilegíveis).')

fd = os.open(CAMINHO, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as f:
    f.write(MODELO.format(secret=secrets.token_hex(32), dados=chave(), indice=chave(), pepper=chave()))
print('Arquivo .env criado.')
print('1) Preencha SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY e DATABASE_URL.')
print('2) Guarde uma cópia do .env em local seguro.')
