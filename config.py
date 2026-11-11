"""Carrega os segredos de fora do código.

Os valores vêm de variáveis de ambiente ou do arquivo .env (que nunca vai para o git).
Para criar o .env pela primeira vez rode:  python gerar_chaves.py
"""
import os

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))


class ConfigFaltando(RuntimeError):
    pass


def segredo(nome):
    """Devolve o segredo ou interrompe com uma mensagem clara. Nunca imprime o valor."""
    valor = os.environ.get(nome, '').strip()
    if not valor or valor.startswith('COLE_') or valor.startswith('TROQUE_'):
        raise ConfigFaltando(
            f'Variável {nome} não configurada. Rode "python gerar_chaves.py" para criar o arquivo .env '
            f'e preencha o que faltar (veja .env.example).')
    return valor


def opcional(nome, padrao=''):
    return os.environ.get(nome, padrao).strip()


def url_do_banco():
    url = segredo('DATABASE_URL')
    # Aceita o formato que o Supabase mostra no painel e ajusta para o driver instalado.
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    if url.startswith('postgresql://'):
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    return url


USAR_HTTPS = opcional('CASTRAMOVEL_HTTPS') == '1'
