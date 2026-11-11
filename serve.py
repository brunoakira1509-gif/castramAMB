import socket

from waitress import serve

from app import app

PORTA = 5000


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))  # não envia nada, só descobre a interface da rede
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


if __name__ == '__main__':
    print('CastraMóvel em execução.')
    print(f'  Neste PC:         http://localhost:{PORTA}')
    print(f'  Outros PCs (LAN): http://{ip_local()}:{PORTA}')
    print('Feche esta janela para encerrar o sistema.')
    serve(app, host='0.0.0.0', port=PORTA, threads=8)
