import os
import sys
import unittest
from datetime import date, time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agenda_regras import (GRADE, categoria_para, data_extensa, hora_texto, ler_data, ler_mes,  # noqa: E402
                           mes_vizinho, montar_grade, opcoes_para_animal, resumo_dia, semanas_do_mes,
                           verificar_vaga)

_ids = iter(range(1, 10_000))


def ag(hora, especie, sexo):
    """Agendamento de mentira: só precisa de id, hora e animal."""
    return SimpleNamespace(id=next(_ids), hora=hora, animal=SimpleNamespace(especie=especie, sexo=sexo))


H0800, H0830, H0930, H1300, H1430 = time(8, 0), time(8, 30), time(9, 30), time(13, 0), time(14, 30)


class GradeTests(unittest.TestCase):
    def test_only_the_five_fixed_times_exist(self):
        self.assertEqual([hora_texto(h.hora) for h in GRADE], ['08:00', '08:30', '09:30', '13:00', '14:30'])

    def test_total_capacity_per_time(self):
        self.assertEqual([h.limite for h in GRADE], [2, 3, 1, 1, 2])

    def test_each_time_accepts_only_its_categories(self):
        casos = {
            H0800: {('gato', 'femea')},
            H0830: {('cao', 'macho'), ('gato', 'macho')},
            H0930: {('cao', 'femea')},
            H1300: {('cao', 'femea')},
            H1430: {('cao', 'macho'), ('cao', 'femea')},
        }
        todos = {(e, s) for e in ('cao', 'gato') for s in ('macho', 'femea')}
        for hora, aceitos in casos.items():
            for especie, sexo in todos:
                atendido = categoria_para(hora, especie, sexo) is not None
                self.assertEqual(atendido, (especie, sexo) in aceitos, (hora, especie, sexo))


class VerificarVagaTests(unittest.TestCase):
    def test_08h00_allows_two_cats_then_blocks_the_third(self):
        dia = []
        self.assertIsNone(verificar_vaga(H0800, 'gato', 'femea', dia)[1])
        dia.append(ag(H0800, 'gato', 'femea'))
        self.assertIsNone(verificar_vaga(H0800, 'gato', 'femea', dia)[1])
        dia.append(ag(H0800, 'gato', 'femea'))
        self.assertIn('esgotadas', verificar_vaga(H0800, 'gato', 'femea', dia)[1])

    def test_08h00_rejects_male_cat_and_dogs(self):
        for especie, sexo in (('gato', 'macho'), ('cao', 'macho'), ('cao', 'femea')):
            self.assertIn('só são atendidos', verificar_vaga(H0800, especie, sexo, [])[1])

    def test_08h30_shares_three_spots_between_male_dogs_and_male_cats(self):
        dia = [ag(H0830, 'cao', 'macho'), ag(H0830, 'gato', 'macho')]
        self.assertIsNone(verificar_vaga(H0830, 'gato', 'macho', dia)[1])
        dia.append(ag(H0830, 'cao', 'macho'))
        self.assertIn('esgotadas', verificar_vaga(H0830, 'cao', 'macho', dia)[1])
        self.assertIn('esgotadas', verificar_vaga(H0830, 'gato', 'macho', dia)[1])

    def test_08h30_rejects_females(self):
        self.assertIn('só são atendidos', verificar_vaga(H0830, 'cao', 'femea', [])[1])
        self.assertIn('só são atendidos', verificar_vaga(H0830, 'gato', 'femea', [])[1])

    def test_single_female_dog_times(self):
        for hora in (H0930, H1300):
            self.assertIsNone(verificar_vaga(hora, 'cao', 'femea', [])[1])
            self.assertIn('esgotadas', verificar_vaga(hora, 'cao', 'femea', [ag(hora, 'cao', 'femea')])[1])
            self.assertIn('só são atendidos', verificar_vaga(hora, 'cao', 'macho', [])[1])
            self.assertIn('só são atendidos', verificar_vaga(hora, 'gato', 'femea', [])[1])

    def test_14h30_has_one_male_dog_spot_and_one_female_dog_spot(self):
        dia = [ag(H1430, 'cao', 'macho')]
        self.assertIn('esgotadas', verificar_vaga(H1430, 'cao', 'macho', dia)[1])
        self.assertIsNone(verificar_vaga(H1430, 'cao', 'femea', dia)[1])
        dia.append(ag(H1430, 'cao', 'femea'))
        self.assertIn('esgotadas', verificar_vaga(H1430, 'cao', 'femea', dia)[1])
        self.assertIn('só são atendidos', verificar_vaga(H1430, 'gato', 'femea', [])[1])
        self.assertIn('só são atendidos', verificar_vaga(H1430, 'gato', 'macho', [])[1])

    def test_14h30_two_males_never_fit_even_if_female_spot_is_free(self):
        dia = [ag(H1430, 'cao', 'macho')]
        self.assertIsNotNone(verificar_vaga(H1430, 'cao', 'macho', dia)[1])

    def test_times_outside_the_grid_are_refused(self):
        for hora in (time(8, 15), time(10, 0), time(12, 0), time(15, 0)):
            self.assertIn('Horário inválido', verificar_vaga(hora, 'cao', 'femea', [])[1])

    def test_animal_without_species_cannot_be_scheduled(self):
        self.assertIn('espécie', verificar_vaga(H0930, None, 'femea', [])[1])
        self.assertIn('espécie', verificar_vaga(H0930, 'cao', '', [])[1])

    def test_seconds_in_database_time_do_not_matter(self):
        self.assertIsNone(verificar_vaga(time(8, 0, 0), 'gato', 'femea', [])[1])

    def test_bookings_of_other_times_do_not_count(self):
        dia = [ag(H0930, 'cao', 'femea')]
        self.assertIsNone(verificar_vaga(H1300, 'cao', 'femea', dia)[1])


class GradeDoDiaTests(unittest.TestCase):
    def test_bookings_go_to_the_right_category(self):
        dia = [ag(H1430, 'cao', 'femea'), ag(H1430, 'cao', 'macho'), ag(H0800, 'gato', 'femea')]
        grade = montar_grade(dia)
        por_hora = {hora_texto(v.horario.hora): v for v in grade.horarios}
        self.assertEqual(por_hora['08:00'].ocupadas, 1)
        self.assertEqual(por_hora['08:00'].livres, 1)
        macho, femea = por_hora['14:30'].vagas
        self.assertEqual(macho.categoria.chave, 'cao_macho')
        self.assertEqual((macho.ocupadas, femea.ocupadas), (1, 1))
        self.assertTrue(macho.cheia and femea.cheia)
        self.assertEqual(grade.total, 3)
        self.assertEqual(grade.avulsos, [])

    def test_old_bookings_outside_the_rules_show_up_as_loose(self):
        grade = montar_grade([ag(time(10, 0), 'cao', 'macho'), ag(H0800, 'cao', 'macho')])
        self.assertEqual(len(grade.avulsos), 2)
        self.assertEqual(grade.total, 2)

    def test_options_for_animal(self):
        grade = montar_grade([ag(H0930, 'cao', 'femea')])
        opcoes = {o['texto']: o for o in opcoes_para_animal(grade, 'cao', 'femea')}
        self.assertEqual(opcoes['09:30']['status'], 'cheio')
        self.assertEqual(opcoes['13:00']['status'], 'livre')
        self.assertEqual(opcoes['14:30']['status'], 'livre')
        self.assertEqual(opcoes['08:00']['status'], 'incompativel')
        self.assertEqual(opcoes['08:30']['status'], 'incompativel')

    def test_options_for_male_cat(self):
        opcoes = {o['texto']: o['status'] for o in opcoes_para_animal(montar_grade([]), 'gato', 'macho')}
        self.assertEqual(opcoes, {'08:00': 'incompativel', '08:30': 'livre', '09:30': 'incompativel',
                                  '13:00': 'incompativel', '14:30': 'incompativel'})

    def test_day_summary_for_calendar(self):
        resumo = resumo_dia([ag(H0800, 'gato', 'femea'), ag(H0800, 'gato', 'femea'), ag(H1300, 'cao', 'femea')])
        self.assertEqual(resumo['total'], 3)
        self.assertEqual(resumo['etiquetas'], [
            {'hora': '08:00', 'n': 2, 'limite': 2, 'cheio': True},
            {'hora': '13:00', 'n': 1, 'limite': 1, 'cheio': True}])


class DatasTests(unittest.TestCase):
    def test_data_extensa(self):
        self.assertEqual(data_extensa(date(2026, 11, 11)), 'Quarta-feira, 11 de novembro de 2026')

    def test_month_navigation_crosses_years(self):
        self.assertEqual(mes_vizinho(2026, 12, 1), (2027, 1))
        self.assertEqual(mes_vizinho(2026, 1, -1), (2025, 12))
        self.assertEqual(mes_vizinho(2026, 6, 0), (2026, 6))

    def test_weeks_cover_the_whole_month_monday_first(self):
        semanas = semanas_do_mes(2026, 11)
        self.assertTrue(all(len(s) == 7 for s in semanas))
        self.assertEqual(semanas[0][0].weekday(), 0)
        dias = [d for s in semanas for d in s]
        self.assertIn(date(2026, 11, 1), dias)
        self.assertIn(date(2026, 11, 30), dias)

    def test_ler_mes_and_ler_data_are_forgiving(self):
        base = date(2026, 11, 11)
        self.assertEqual(ler_mes('2027-03', base), (2027, 3))
        for ruim in (None, '', 'abc', '2026-13', '1999-01', '2026'):
            self.assertEqual(ler_mes(ruim, base), (2026, 11))
        self.assertEqual(ler_data('2026-11-12'), date(2026, 11, 12))
        self.assertIsNone(ler_data('12/11/2026'))
        self.assertIsNone(ler_data(None))


if __name__ == '__main__':
    unittest.main()
