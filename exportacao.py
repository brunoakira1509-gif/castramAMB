"""Exportação em CSV de tutores e microchips para enviar à plataforma AnimallTAG (animalltag.net).

ATENÇÃO: o modelo oficial de importação do AnimallTAG não pôde ser consultado (fica atrás do login da plataforma).
As colunas abaixo são PROVISÓRIAS. Para deixá-las idênticas ao modelo:
  1. baixe o modelo de planilha dentro da sua conta AnimallTAG;
  2. copie os nomes das colunas, na mesma ordem, para a lista COLUNAS;
  3. ajuste SEPARADOR se o modelo usar vírgula, e troque LAYOUT_CONFIRMADO para True.

Cada coluna é (cabeçalho no CSV, campo). Campos disponíveis em cada linha:
  microchip, animal, especie, raca, sexo, tutor, cpf, telefone, endereco, numero, data
"""
import csv
import io
import re

LAYOUT_CONFIRMADO = False
SEPARADOR = ';'  # ';' abre direto no Excel em português; mude para ',' se o modelo da plataforma pedir

COLUNAS = (
    ('Microchip', 'microchip'),
    ('Nome do animal', 'animal'),
    ('Espécie', 'especie'),
    ('Raça', 'raca'),
    ('Sexo', 'sexo'),
    ('Nome do proprietário', 'tutor'),
    ('CPF do proprietário', 'cpf'),
    ('Telefone do proprietário', 'telefone'),
    ('Endereço do proprietário', 'endereco'),
    ('Número', 'numero'),
)

# Campos que são só números: saem sem pontos, traços ou espaços.
CAMPOS_NUMERICOS = {'microchip', 'cpf', 'telefone'}


def so_digitos(texto):
    return re.sub(r'\D', '', texto or '')


def seguro_csv(valor):
    """Evita injeção de fórmula: texto começando com = + - @ viraria fórmula ao abrir no Excel."""
    if isinstance(valor, str) and valor[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + valor
    return valor


def valor_da_coluna(linha, campo):
    valor = linha.get(campo, '')
    if campo in CAMPOS_NUMERICOS:
        return so_digitos(valor)
    return seguro_csv(valor if valor is not None else '')


def montar_csv(linhas):
    """Devolve os bytes do CSV (UTF-8 com BOM, para o Excel reconhecer os acentos)."""
    saida = io.StringIO(newline='')
    escritor = csv.writer(saida, delimiter=SEPARADOR, lineterminator='\r\n')
    escritor.writerow([cabecalho for cabecalho, _ in COLUNAS])
    for linha in linhas:
        escritor.writerow([valor_da_coluna(linha, campo) for _, campo in COLUNAS])
    return saida.getvalue().encode('utf-8-sig')
