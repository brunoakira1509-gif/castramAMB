import csv
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import exportacao  # noqa: E402


def ler(conteudo):
    texto = conteudo.decode('utf-8-sig')
    return list(csv.reader(io.StringIO(texto), delimiter=exportacao.SEPARADOR))


LINHA = {'microchip': '985 112 345 678 901', 'animal': 'Mimi', 'especie': 'Gato', 'raca': 'SRD', 'sexo': 'Fêmea',
         'tutor': 'Maria de Souza', 'cpf': '123.456.789-09', 'telefone': '(15) 99999-0000',
         'endereco': 'Rua das Flores', 'numero': '10', 'data': '2026-11-12'}


class ExportacaoTests(unittest.TestCase):
    def test_header_matches_configured_columns_and_has_bom(self):
        conteudo = exportacao.montar_csv([])
        self.assertTrue(conteudo.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(ler(conteudo)[0], [c for c, _ in exportacao.COLUNAS])

    def test_numeric_fields_are_digits_only(self):
        linha = ler(exportacao.montar_csv([LINHA]))[1]
        por_campo = {campo: linha[i] for i, (_, campo) in enumerate(exportacao.COLUNAS)}
        self.assertEqual(por_campo['microchip'], '985112345678901')
        self.assertEqual(por_campo['cpf'], '12345678909')
        self.assertEqual(por_campo['telefone'], '15999990000')
        self.assertEqual(por_campo['tutor'], 'Maria de Souza')
        self.assertEqual(por_campo['sexo'], 'Fêmea')

    def test_formula_injection_is_neutralised_in_text_fields(self):
        linha = dict(LINHA, tutor='=HYPERLINK("http://x")', animal='@cmd', endereco='-1+1')
        por_campo = {campo: v for (_, campo), v in zip(exportacao.COLUNAS, ler(exportacao.montar_csv([linha]))[1])}
        self.assertTrue(por_campo['tutor'].startswith("'="))
        self.assertTrue(por_campo['animal'].startswith("'@"))
        self.assertTrue(por_campo['endereco'].startswith("'-"))

    def test_values_with_separator_and_quotes_survive_round_trip(self):
        linha = dict(LINHA, tutor='Silva; "Júnior"', endereco='Rua A; casa 2')
        lida = ler(exportacao.montar_csv([linha]))[1]
        por_campo = {campo: v for (_, campo), v in zip(exportacao.COLUNAS, lida)}
        self.assertEqual(por_campo['tutor'], 'Silva; "Júnior"')
        self.assertEqual(por_campo['endereco'], 'Rua A; casa 2')
        self.assertEqual(len(lida), len(exportacao.COLUNAS))

    def test_one_row_per_animal_and_crlf(self):
        conteudo = exportacao.montar_csv([LINHA, dict(LINHA, animal='Rex')])
        self.assertEqual(len(ler(conteudo)), 3)
        self.assertIn(b'\r\n', conteudo)


if __name__ == '__main__':
    unittest.main()
