@echo off
net session >nul 2>&1
if errorlevel 1 (
    echo Clique com o botao direito neste arquivo e escolha Executar como administrador.
    pause
    exit /b 1
)
netsh advfirewall firewall delete rule name="CastraMovel" >nul 2>&1
netsh advfirewall firewall add rule name="CastraMovel" dir=in action=allow protocol=TCP localport=5000 profile=private
echo.
echo Porta 5000 liberada somente para redes privadas.
pause
