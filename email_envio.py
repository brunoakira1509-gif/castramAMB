"""Envio de e-mail (SMTP) com o código de verificação. As credenciais vêm do .env."""
import smtplib
import ssl
from email.message import EmailMessage

from config import opcional, segredo


def validar_config():
    """Falha na partida se o SMTP não estiver configurado (sem e-mail ninguém consegue entrar)."""
    for nome in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM'):
        segredo(nome)


def montar_mensagem(destino, codigo, minutos, remetente):
    msg = EmailMessage()
    msg['Subject'] = f'CastraMóvel: seu código de acesso é {codigo}'
    msg['From'] = remetente
    msg['To'] = destino
    msg.set_content(
        f'Seu código de verificação do CastraMóvel é:\n\n    {codigo}\n\n'
        f'Ele vale por {minutos} minutos e só pode ser usado uma vez.\n\n'
        'Se não foi você que tentou entrar, ignore este e-mail e troque sua senha.\n'
        'Nunca informe este código a ninguém.\n')
    return msg


def enviar_codigo(destino, codigo, minutos):
    host, usuario = segredo('SMTP_HOST'), segredo('SMTP_USER')
    senha, remetente = segredo('SMTP_PASSWORD'), segredo('SMTP_FROM')
    porta = int(opcional('SMTP_PORT', '587'))
    msg = montar_mensagem(destino, codigo, minutos, remetente)
    contexto = ssl.create_default_context()  # valida o certificado do servidor de e-mail
    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, context=contexto, timeout=15) as servidor:
            servidor.login(usuario, senha)
            servidor.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=15) as servidor:
            servidor.starttls(context=contexto)  # nunca envia senha/código sem TLS
            servidor.login(usuario, senha)
            servidor.send_message(msg)
