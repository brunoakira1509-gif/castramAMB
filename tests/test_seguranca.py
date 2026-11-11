import base64, os, sys, types, unittest

# Stub só para este ambiente sem SQLAlchemy; no projeto real o import é o verdadeiro.
if 'sqlalchemy' not in sys.modules:
    try:
        import sqlalchemy  # noqa
    except ImportError:
        m = types.ModuleType('sqlalchemy'); t = types.ModuleType('sqlalchemy.types')
        t.Text = object
        class TypeDecorator:  # noqa
            def __init__(self, *a, **k): pass
        t.TypeDecorator = TypeDecorator
        sys.modules['sqlalchemy'] = m; sys.modules['sqlalchemy.types'] = t

def k(): return base64.urlsafe_b64encode(os.urandom(32)).decode()
os.environ.update(CASTRAMOVEL_DATA_KEY=k(), CASTRAMOVEL_INDEX_KEY=k(), CASTRAMOVEL_PEPPER=k())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seguranca as s
from werkzeug.security import generate_password_hash


class T(unittest.TestCase):
    def test_ida_e_volta_com_acentos(self):
        for txt in ['Maria da Conceição', '123.456.789-09', '', 'Rua "A" <b>x</b>; DROP TABLE tutor;--']:
            self.assertEqual(s.decifrar_texto(s.cifrar_texto(txt, 'tutor.nome'), 'tutor.nome'), txt)

    def test_none(self):
        self.assertIsNone(s.cifrar_texto(None, 'a')); self.assertIsNone(s.decifrar_texto(None, 'a'))

    def test_nao_guarda_texto_claro_e_nonce_aleatorio(self):
        a, b = s.cifrar_texto('Maria', 'x'), s.cifrar_texto('Maria', 'x')
        self.assertNotEqual(a, b); self.assertNotIn('Maria', a); self.assertTrue(a.startswith('v1:'))

    def test_amarrado_a_coluna(self):
        c = s.cifrar_texto('segredo', 'tutor.cpf')
        with self.assertRaises(s.ErroDeCriptografia): s.decifrar_texto(c, 'tutor.telefone')

    def test_adulteracao_detectada(self):
        c = s.cifrar_texto('segredo', 'x'); raw = bytearray(base64.urlsafe_b64decode(c[3:])); raw[-1] ^= 1
        with self.assertRaises(s.ErroDeCriptografia):
            s.decifrar_texto('v1:' + base64.urlsafe_b64encode(bytes(raw)).decode(), 'x')

    def test_texto_claro_no_banco_e_recusado(self):
        with self.assertRaises(s.ErroDeCriptografia): s.decifrar_texto('Maria', 'x')

    def test_arquivos(self):
        dados = os.urandom(5000)
        blob = s.cifrar_bytes(dados, 'documento.arquivo')
        self.assertEqual(s.decifrar_bytes(blob, 'documento.arquivo'), dados)
        with self.assertRaises(s.ErroDeCriptografia): s.decifrar_bytes(blob[:-1] + bytes([blob[-1] ^ 1]), 'documento.arquivo')
        with self.assertRaises(s.ErroDeCriptografia): s.decifrar_bytes(b'%PDF-1.4 em claro', 'documento.arquivo')

    def test_indice_cego(self):
        self.assertEqual(s.indice_cego('12345678909', 'tutor.cpf'), s.indice_cego('12345678909', 'tutor.cpf'))
        self.assertNotEqual(s.indice_cego('12345678909', 'tutor.cpf'), s.indice_cego('12345678909', 'animal.microchip'))
        self.assertIsNone(s.indice_cego('', 'x')); self.assertNotIn('12345678909', s.indice_cego('12345678909', 'x'))

    def test_normalizar(self):
        self.assertEqual(s.normalizar('JOÃO Conceição'), 'joao conceicao')

    def test_senha(self):
        h = s.hash_senha('uma senha forte 123')
        self.assertTrue(h.startswith('scrypt:32768:8:1$')); self.assertNotIn('forte', h)
        self.assertEqual(s.verificar_senha('uma senha forte 123', h), (True, False))
        self.assertEqual(s.verificar_senha('errada', h), (False, False))
        self.assertEqual(s.verificar_senha('x', None), (False, False))
        self.assertEqual(s.verificar_senha('a' * 2000, h), (False, False))

    def test_hash_antigo_sem_pepper_e_atualizado(self):
        antigo = generate_password_hash('senhaantiga1')
        self.assertEqual(s.verificar_senha('senhaantiga1', antigo), (True, True))
        self.assertEqual(s.verificar_senha('outra', antigo), (False, False))

    def test_pepper_faz_diferenca(self):
        h = s.hash_senha('abc12345678')
        self.assertFalse(__import__('werkzeug.security', fromlist=['x']).check_password_hash(h, 'abc12345678'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
