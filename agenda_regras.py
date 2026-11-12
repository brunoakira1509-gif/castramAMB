"""Regras da agenda de castração: horários fixos, categorias e número de vagas.

Este módulo não depende de Flask nem do banco: só recebe objetos com os atributos
`hora` e `animal` (com `.especie` e `.sexo`). Assim as regras ficam fáceis de testar e de mudar.

COMO ALTERAR AS VAGAS: edite apenas a lista GRADE logo abaixo. O resto do sistema
(tela inicial, calendário, agendamento e validação no servidor) acompanha sozinho.
"""
import calendar
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

FUSO = 'America/Sao_Paulo'

DIAS_SEMANA = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
DIAS_CURTOS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
         'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']


# ---------------------------------------------------------------------------
# Data de hoje (no fuso do Brasil, mesmo que o servidor esteja em outro fuso, como o Vercel)
# ---------------------------------------------------------------------------
def agora():
    try:
        return datetime.now(ZoneInfo(FUSO))
    except Exception:  # sem base de fusos (Windows sem tzdata): usa o relógio do computador
        return datetime.now()


def hoje():
    return agora().date()


def data_extensa(dia):
    return f'{DIAS_SEMANA[dia.weekday()].capitalize()}, {dia.day} de {MESES[dia.month - 1]} de {dia.year}'


def dia_util(dia):
    return dia.weekday() < 5


def hora_texto(hora):
    return hora.strftime('%H:%M')


# ---------------------------------------------------------------------------
# A grade de horários
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Categoria:
    chave: str          # identifica a categoria dentro do horário
    rotulo: str         # nome curto mostrado nas telas
    detalhe: str        # explicação mostrada ao lado
    aceita: frozenset   # pares (espécie, sexo) aceitos: espécie 'cao'/'gato', sexo 'macho'/'femea'
    limite: int         # máximo de animais desta categoria neste horário

    def aceita_animal(self, especie, sexo):
        return (especie, sexo) in self.aceita

    @property
    def titulo(self):
        return f'{self.rotulo} ({self.detalhe})'


@dataclass(frozen=True)
class Horario:
    hora: time
    categorias: tuple

    @property
    def limite(self):
        return sum(c.limite for c in self.categorias)


_GATA = Categoria('gata', 'Gatas', 'felinos fêmeas', frozenset({('gato', 'femea')}), 2)
_MACHOS = Categoria('machos', 'Machos', 'cães ou gatos machos',
                    frozenset({('cao', 'macho'), ('gato', 'macho')}), 3)
_CADELA = Categoria('cadela', 'Cadela', 'cão fêmea', frozenset({('cao', 'femea')}), 1)
_CAO_MACHO = Categoria('cao_macho', 'Cão macho', 'cão macho', frozenset({('cao', 'macho')}), 1)

GRADE = (
    Horario(time(8, 0), (_GATA,)),                 # até 2 gatas
    Horario(time(8, 30), (_MACHOS,)),              # até 3 machos no total (cães e/ou gatos)
    Horario(time(9, 30), (_CADELA,)),              # 1 cadela
    Horario(time(13, 0), (_CADELA,)),              # 1 cadela
    Horario(time(14, 30), (_CAO_MACHO, _CADELA)),  # 1 cão macho + 1 cadela
)


def _normalizar(hora):
    return hora.replace(second=0, microsecond=0)


def horario_da_grade(hora):
    hora = _normalizar(hora)
    for horario in GRADE:
        if horario.hora == hora:
            return horario
    return None


def categoria_para(hora, especie, sexo):
    """Categoria em que o animal entraria nesse horário, ou None se o horário não o atende."""
    horario = horario_da_grade(hora)
    if horario is None:
        return None
    for categoria in horario.categorias:
        if categoria.aceita_animal(especie, sexo):
            return categoria
    return None


def resumo_horario(horario):
    """Texto como 'Gatas (felinos fêmeas)' ou 'Cão macho (cão macho) e Cadela (cão fêmea)'."""
    return ' e '.join(c.titulo for c in horario.categorias)


def lista_horarios_texto():
    return ', '.join(hora_texto(h.hora) for h in GRADE)


# ---------------------------------------------------------------------------
# Ocupação de um dia
# ---------------------------------------------------------------------------
@dataclass
class VagaView:
    """Uma categoria dentro de um horário, com os animais já agendados nela."""
    categoria: Categoria
    agendamentos: list = field(default_factory=list)

    @property
    def ocupadas(self):
        return len(self.agendamentos)

    @property
    def livres(self):
        return max(0, self.categoria.limite - self.ocupadas)

    @property
    def cheia(self):
        return self.livres == 0


@dataclass
class HorarioView:
    horario: Horario
    vagas: list

    @property
    def ocupadas(self):
        return sum(v.ocupadas for v in self.vagas)

    @property
    def livres(self):
        return sum(v.livres for v in self.vagas)

    @property
    def limite(self):
        return self.horario.limite


@dataclass
class GradeDia:
    horarios: list
    avulsos: list  # agendamentos que não se encaixam na grade (ex.: feitos antes das regras novas)

    @property
    def total(self):
        return sum(h.ocupadas for h in self.horarios) + len(self.avulsos)


def montar_grade(agendamentos):
    """Distribui os agendamentos de um dia nos horários e categorias da grade."""
    por_hora = {h.hora: HorarioView(h, [VagaView(c) for c in h.categorias]) for h in GRADE}
    avulsos = []
    for ag in sorted(agendamentos, key=lambda a: (a.hora, a.id or 0)):
        vista = por_hora.get(_normalizar(ag.hora))
        destino = None
        if vista:
            for vaga in vista.vagas:
                if vaga.categoria.aceita_animal(ag.animal.especie, ag.animal.sexo):
                    destino = vaga
                    break
        if destino:
            destino.agendamentos.append(ag)
        else:
            avulsos.append(ag)
    return GradeDia(list(por_hora.values()), avulsos)


def resumo_dia(agendamentos):
    """Dados para as 'etiquetas' de cada dia do calendário: [{'hora', 'n', 'limite', 'cheio'}]."""
    grade = montar_grade(agendamentos)
    etiquetas = [{'hora': hora_texto(h.horario.hora), 'n': h.ocupadas, 'limite': h.limite,
                  'cheio': h.livres == 0} for h in grade.horarios if h.ocupadas]
    for ag in grade.avulsos:
        etiquetas.append({'hora': hora_texto(ag.hora), 'n': 1, 'limite': None, 'cheio': False})
    etiquetas.sort(key=lambda e: e['hora'])
    return {'total': len(agendamentos), 'etiquetas': etiquetas}


# ---------------------------------------------------------------------------
# Validação de um novo agendamento
# ---------------------------------------------------------------------------
def verificar_vaga(hora, especie, sexo, agendamentos_do_dia):
    """Devolve (categoria, erro). `erro` é None quando o animal pode ser agendado nesse horário."""
    horario = horario_da_grade(hora)
    if horario is None:
        return None, f'Horário inválido. Os horários de atendimento são: {lista_horarios_texto()}.'
    if especie not in ('cao', 'gato') or sexo not in ('macho', 'femea'):
        return None, 'Informe a espécie e o sexo do animal no cadastro antes de agendar.'
    categoria = categoria_para(hora, especie, sexo)
    if categoria is None:
        return None, f'Às {hora_texto(horario.hora)} só são atendidos: {resumo_horario(horario)}.'
    ocupadas = sum(1 for ag in agendamentos_do_dia
                   if _normalizar(ag.hora) == horario.hora
                   and categoria.aceita_animal(ag.animal.especie, ag.animal.sexo))
    if ocupadas >= categoria.limite:
        return categoria, (f'Vagas esgotadas às {hora_texto(horario.hora)} para '
                           f'{categoria.rotulo.lower()} ({ocupadas}/{categoria.limite}).')
    return categoria, None


def opcoes_para_animal(grade, especie, sexo):
    """Lista de horários do dia, dizendo se cada um está livre, lotado ou não atende esse animal."""
    opcoes = []
    for vista in grade.horarios:
        horario = vista.horario
        categoria = categoria_para(horario.hora, especie, sexo)
        opcao = {'hora': horario.hora, 'texto': hora_texto(horario.hora), 'rotulo': '', 'livres': 0,
                 'limite': 0, 'status': 'incompativel', 'motivo': f'Atende: {resumo_horario(horario)}'}
        if categoria is not None:
            vaga = next(v for v in vista.vagas if v.categoria is categoria)
            opcao.update(rotulo=categoria.titulo, livres=vaga.livres, limite=categoria.limite,
                         status='livre' if vaga.livres else 'cheio',
                         motivo='' if vaga.livres else 'Vagas esgotadas')
        opcoes.append(opcao)
    return opcoes


# ---------------------------------------------------------------------------
# Calendário mensal
# ---------------------------------------------------------------------------
def semanas_do_mes(ano, mes):
    """Semanas (segunda a domingo) que cobrem o mês, incluindo dias dos meses vizinhos."""
    return calendar.Calendar(firstweekday=0).monthdatescalendar(ano, mes)


def mes_vizinho(ano, mes, passo):
    indice = (ano * 12 + (mes - 1)) + passo
    return indice // 12, indice % 12 + 1


def ler_data(texto):
    try:
        return datetime.strptime(texto or '', '%Y-%m-%d').date()
    except ValueError:
        return None


def ler_mes(texto, padrao):
    """Interpreta 'AAAA-MM'. Se vier algo inválido, usa o mês de `padrao` (uma data)."""
    try:
        ano, mes = (int(p) for p in (texto or '').split('-'))
        if 2000 <= ano <= 2100 and 1 <= mes <= 12:
            return ano, mes
    except ValueError:
        pass
    return padrao.year, padrao.month



# ---------------------------------------------------------------------------
# Dia do atendimento: presença e navegação entre dias úteis
# ---------------------------------------------------------------------------
def resumo_presenca(agendamentos):
    """Contagem para o topo da tela de atendimento. `presente`: True = compareceu, False = faltou, None = aguardando."""
    presentes = sum(1 for ag in agendamentos if ag.presente is True)
    faltaram = sum(1 for ag in agendamentos if ag.presente is False)
    total = len(agendamentos)
    return {'total': total, 'presentes': presentes, 'faltaram': faltaram, 'aguardando': total - presentes - faltaram}


def dia_util_vizinho(dia, passo):
    """Dia útil anterior (passo=-1) ou seguinte (passo=1), pulando sábado e domingo."""
    vizinho = dia + timedelta(days=passo)
    while not dia_util(vizinho):
        vizinho += timedelta(days=passo)
    return vizinho
