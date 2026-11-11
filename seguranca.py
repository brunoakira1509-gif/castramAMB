"""Criptografia dos dados, índices cegos e hash de senhas.

- Campos sensíveis: AES-256-GCM (autenticado). Cada valor tem nonce aleatório próprio e fica
  "amarrado" à coluna (AAD): copiar o texto cifrado de uma coluna para outra não funciona.
- Busca exata (CPF, microchip): índice cego = HMAC-SHA256 com chave separada. Dá para checar
  duplicidade no banco sem guardar o valor em claro.
- Senhas: HMAC com um "pepper" secreto (fora do banco) + scrypt com salt por usuário.
"""
import base64
import hashlib
import hmac
import os
import secrets
import unicodedata

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator
from werkzeug.security import check_password_hash, generate_password_hash

from config import segredo

PREFIXO = 'v1:'
MAGIC_ARQUIVO = b'CMF1'


class ErroDeCriptografia(Exception):
    pass


def _decodificar_chave(nome, exigir_32=True):
    bruto = segredo(nome)
    try:
        chave = base64.urlsafe_b64decode(bruto + '=' * (-len(bruto) % 4))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f'{nome} inválida: não é base64.') from exc
    if exigir_32 and len(chave) != 32:
        raise RuntimeError(f'{nome} inválida: precisa ter 32 bytes. Gere com "python gerar_chaves.py".')
    return chave


_cache = {}


def _chaves():
    if not _cache:
        _cache['dados'] = AESGCM(_decodificar_chave('CASTRAMOVEL_DATA_KEY'))
        _cache['indice'] = _decodificar_chave('CASTRAMOVEL_INDEX_KEY')
        _cache['pepper'] = _decodificar_chave('CASTRAMOVEL_PEPPER')
    return _cache


def validar_chaves():
    """Chame na inicialização: falha cedo se faltar alguma chave."""
    _chaves()


# ---------- Texto ----------
def cifrar_texto(texto, aad):
    if texto is None:
        return None
    nonce = os.urandom(12)
    cifrado = _chaves()['dados'].encrypt(nonce, texto.encode('utf-8'), aad.encode('utf-8'))
    return PREFIXO + base64.urlsafe_b64encode(nonce + cifrado).decode('ascii')


def decifrar_texto(valor, aad):
    if valor is None:
        return None
    if not valor.startswith(PREFIXO):
        raise ErroDeCriptografia('Valor no banco não está no formato criptografado esperado.')
    try:
        bruto = base64.urlsafe_b64decode(valor[len(PREFIXO):])
        return _chaves()['dados'].decrypt(bruto[:12], bruto[12:], aad.encode('utf-8')).decode('utf-8')
    except (InvalidTag, ValueError) as exc:
        raise ErroDeCriptografia(f'Falha ao descriptografar {aad}: chave errada ou dado adulterado.') from exc


class TextoCriptografado(TypeDecorator):
    """Coluna que cifra ao gravar e descriptografa ao ler. O resto do código vê texto normal."""
    impl = Text
    cache_ok = True

    def __init__(self, aad):
        super().__init__()
        self.aad = aad

    def process_bind_param(self, value, dialect):
        return cifrar_texto(value, self.aad)

    def process_result_value(self, value, dialect):
        return decifrar_texto(value, self.aad)


# ---------- Arquivos ----------
def cifrar_bytes(dados, aad):
    nonce = os.urandom(12)
    return MAGIC_ARQUIVO + nonce + _chaves()['dados'].encrypt(nonce, dados, aad.encode('utf-8'))


def decifrar_bytes(blob, aad):
    if not blob.startswith(MAGIC_ARQUIVO):
        raise ErroDeCriptografia('Arquivo não está no formato criptografado esperado.')
    corpo = blob[len(MAGIC_ARQUIVO):]
    try:
        return _chaves()['dados'].decrypt(corpo[:12], corpo[12:], aad.encode('utf-8'))
    except InvalidTag as exc:
        raise ErroDeCriptografia('Falha ao descriptografar arquivo.') from exc


# ---------- Índice cego e busca ----------
def indice_cego(valor, rotulo):
    if not valor:
        return None
    mensagem = f'{rotulo}\x00{valor}'.encode('utf-8')
    return hmac.new(_chaves()['indice'], mensagem, hashlib.sha256).hexdigest()


def normalizar(texto):
    """Minúsculo e sem acento, para buscas que ignoram maiúsculas/acentos."""
    sem_acento = unicodedata.normalize('NFKD', texto or '')
    return ''.join(c for c in sem_acento if not unicodedata.combining(c)).casefold()


# ---------- Senhas ----------
SENHA_MAX = 1024
METODO_HASH = 'scrypt:32768:8:1'


def _preparar(senha):
    # O pepper vive só no .env. Quem roubar apenas o banco não consegue nem testar senhas.
    return base64.b64encode(hmac.new(_chaves()['pepper'], senha.encode('utf-8'), hashlib.sha256).digest()).decode()


def hash_senha(senha):
    return generate_password_hash(_preparar(senha), method=METODO_HASH, salt_length=16)


_falso = {}


def verificar_senha(senha, hash_guardado):
    """Devolve (ok, precisa_atualizar). Aceita hashes antigos (sem pepper) e pede atualização."""
    if len(senha) > SENHA_MAX:
        return False, False
    if hash_guardado is None:  # usuário inexistente: gasta o mesmo tempo para não revelar quem existe
        if 'h' not in _falso:
            _falso['h'] = hash_senha('senha-falsa-para-igualar-tempo')
        check_password_hash(_falso['h'], _preparar(senha))
        return False, False
    if check_password_hash(hash_guardado, _preparar(senha)):
        return True, not hash_guardado.startswith('scrypt:32768:8:1$')
    if check_password_hash(hash_guardado, senha):  # hash antigo, de antes do pepper
        return True, True
    return False, False


# ---------- Código de verificação por e-mail ----------
def gerar_codigo():
    return f'{secrets.randbelow(10 ** 6):06d}'


def hash_codigo(token, codigo):
    """O código nunca é guardado: só o HMAC dele, amarrado ao token daquela tentativa de login."""
    return indice_cego(f'{token}\x00{codigo}', 'verificacao_login')


def codigo_confere(token, codigo, hash_guardado):
    return hmac.compare_digest(hash_codigo(token, codigo) or '', hash_guardado)
