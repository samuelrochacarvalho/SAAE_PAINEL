@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title SAAE PAINEL - Instalacao de dependencias
set "PEND=0"
set "PY="
set "REPORT=%~dp0atenção.txt"
if exist "%REPORT%" del /q "%REPORT%"
if exist "%REPORT%" (echo Nao foi possivel atualizar o relatorio. & pause & exit /b 1)
echo ==========================================
echo SAAE PAINEL - Instalacao de dependencias
echo ==========================================
call :preparar_pasta
if errorlevel 1 goto :windows
call :preparar_vc
call :preparar_webview
call :detectar_python
if not defined PY call :instalar_python
if defined PY echo [OK] Python compativel detectado.
call :preparar_cloudflared
if not defined PY goto :sem_python
%PY% --version
%PY% -m pip --version >nul 2>&1
if errorlevel 1 %PY% -m ensurepip --upgrade
rem Resolve o executavel sem executar um caminho entre aspas dentro de FOR /F.
set "PYEXE="
set "PYTMP=%TEMP%\saae_python_%RANDOM%_%RANDOM%.txt"
%PY% -c "import sys; print(sys.executable)" >"%PYTMP%"
set /p "PYEXE=" <"%PYTMP%"
del /q "%PYTMP%"
if not defined PYEXE goto :sem_pip
for %%P in ("%PYEXE%") do set "PATH=%%~dpPScripts;%%~dpP;%PATH%"
pip --version
if errorlevel 1 goto :sem_pip
%PY% -c "import pip, shutil, pathlib, sysconfig; p=shutil.which('pip'); assert p and pathlib.Path(p).resolve().parent == pathlib.Path(sysconfig.get_path('scripts')).resolve()"
if errorlevel 1 goto :sem_pip
call :biblioteca pip pip 26.3
call :biblioteca Adafruit_IO adafruit-io 2.8.0
call :biblioteca webview pywebview 6.2.1
call :biblioteca truststore truststore 0.10.5
call :biblioteca PIL pillow 11.3.0
%PY% -c "import tkinter, sqlite3" >nul 2>&1
if errorlevel 1 call :pendencia "Python sem tkinter ou sqlite3. Reinstale com Tcl/Tk."
goto :windows
:sem_pip
call :pendencia "pip indisponivel ou associado a outro Python. Confira PATH e execute novamente."
goto :windows
:sem_python
call :pendencia "Python x64 3.13 ou superior indisponivel. Execute o instalador local e tente novamente."
:windows
echo.
echo Verificando PHP...
call :preparar_php
if not exist "runtime\php\php.exe" (
    echo [PENDENTE] PHP indisponivel. Confira a extracao acima.
    call :pendencia "PHP indisponivel. Extraia runtime/php.rar em runtime, preservando a pasta php. https://www.7-zip.org/"
) else (
    "runtime\php\php.exe" -v
    if errorlevel 1 (
        echo [PENDENTE] PHP nao iniciou. Verifique o Visual C++ e a arquitetura.
        call :pendencia "PHP nao iniciou. Confira Visual C++ e arquitetura do PHP."
    ) else (
        "runtime\php\php.exe" --ini
        for %%E in (openssl sqlite3 pdo_sqlite) do (
            "runtime\php\php.exe" -r "exit(extension_loaded('%%E') ? 0 : 1);"
            if errorlevel 1 (
                echo [PENDENTE] Habilite %%E no php.ini.
                call :pendencia "Extensao PHP %%E ausente. Confira runtime/php/php.ini."
            ) else echo [OK] Extensao %%E
        )
        "runtime\php\php.exe" -r "exit(extension_loaded('curl') ? 1 : 0);"
        if errorlevel 1 (
            echo [PENDENTE] cURL habilitado. Desabilite extension=curl no php.ini.
            call :pendencia "Extensao PHP curl habilitada. Comente extension=curl com ponto e virgula no php.ini carregado, conforme indicado acima."
        ) else echo [OK] Extensao curl desabilitada
    )
)

echo.
call :configurar_mqtt
echo Verificando arquivos do projeto...
for %%F in ("launcher.pyw" "atualizador.pyw" "index.php" "mqtt\cliente.py" "mqtt\config.py" "config\comandos.php" "assets\launcher_fundo.png") do (
    if exist "%%~F" (echo [OK] %%~F) else (
        echo [PENDENTE] %%~F
        call :pendencia "Arquivo ausente: %%~F. Restaure do projeto ou configure localmente."
    )
)
if exist "dependencias\cloudflared.exe" (echo [OK] Cloudflared local) else call :pendencia "Arquivo do projeto ausente: dependencias/cloudflared.exe. Confira cloudflared.zip na Release."
echo.
call :preparar_banco
call :criar_atalho
echo.
if "%PEND%"=="0" (
    echo Verificacoes concluidas sem pendencias detectadas.
    echo Teste o launcher manualmente antes de operar os equipamentos.
    pause
    exit /b 0
)
echo Verificacoes concluidas com %PEND% pendencia^(s^).
echo Corrija os itens indicados e execute novamente.
echo Relatorio: "%REPORT%"
start "" notepad.exe "%REPORT%"
pause
exit /b 1

:pendencia
set /a PEND+=1 >nul
echo [PENDENTE] "%~1"
if not exist "%REPORT%" >"%REPORT%" echo SAAE PAINEL - Dependencias pendentes - %date% %time%
>>"%REPORT%" echo - "%~1"
exit /b 0

:biblioteca
set "DEPLOG=%TEMP%\saae_dep_%RANDOM%_%RANDOM%.log"
%PY% -c "from importlib.metadata import version; from pip._vendor.packaging.version import Version; v=version('%~2'); print('%~2: '+v); raise SystemExit(0 if Version(v) >= Version('%~3') else 1)" >"%DEPLOG%" 2>&1
if not errorlevel 1 goto :validar_biblioteca
echo Instalando ou atualizando %~2 para %~3...
if /i "%~2"=="pip" (
    %PY% -m pip install --upgrade "pip>=26.3" >>"%DEPLOG%" 2>&1
) else (
    pip install --upgrade "%~2" >>"%DEPLOG%" 2>&1
)
if errorlevel 1 goto :biblioteca_falhou
:validar_biblioteca
%PY% -c "from importlib.metadata import version; from pip._vendor.packaging.version import Version; import %~1; v=version('%~2'); print('%~2: '+v); assert Version(v) >= Version('%~3')" >>"%DEPLOG%" 2>&1
if errorlevel 1 goto :biblioteca_falhou
echo [OK] %~2 instalada e validada.
type "%DEPLOG%"
del /q "%DEPLOG%"
exit /b 0
:biblioteca_falhou
call :pendencia "Falha em %~2 (minimo %~3). https://pypi.org/project/%~2/"
type "%DEPLOG%"
>>"%REPORT%" type "%DEPLOG%"
del /q "%DEPLOG%"
exit /b 1

:preparar_php
if exist "runtime\php\php.exe" (
    if not exist "runtime\php\php.ini" call :pendencia "php.ini ausente. Restaure a configuracao original do RAR."
    echo [OK] PHP ja extraido. Preservando instalacao existente.
    exit /b 0
)
if exist "runtime\php" (
    echo [AVISO] Pasta runtime\php existente, mas sem php.exe.
    echo Confira a pasta manualmente. Nenhum arquivo sera sobrescrito.
    exit /b 1
)
if not exist "runtime\php.rar" (
    echo [ERRO] Arquivo runtime\php.rar nao encontrado.
    exit /b 1
)
where tar.exe >nul 2>&1
if errorlevel 1 (
    echo [ERRO] tar.exe indisponivel. Extraia o RAR manualmente em runtime.
    exit /b 1
)
set "STAGE=runtime\php_extracao_%RANDOM%_%RANDOM%"
mkdir "%STAGE%" || exit /b 1
echo Extraindo PHP configurado...
tar.exe -xf "runtime\php.rar" -C "%STAGE%"
if errorlevel 1 goto :extracao_falhou
if not exist "%STAGE%\php\php.exe" goto :extracao_falhou
if not exist "%STAGE%\php\php.ini" goto :extracao_falhou
if exist "runtime\php" goto :extracao_falhou
move "%STAGE%\php" "runtime\php" >nul
if errorlevel 1 goto :extracao_falhou
rd /s /q "%STAGE%"
echo [OK] PHP extraido com a configuracao original.
exit /b 0
:extracao_falhou
rd /s /q "%STAGE%"
echo [ERRO] Falha na extracao ou estrutura inesperada do RAR.
echo Se o tar nao suportar RAR, use WinRAR ou 7-Zip para extrair em runtime.
exit /b 1

:preparar_banco
echo Verificando banco SQLite...
if exist "dados\saae.db" (
    echo [OK] Banco existente. Nenhum dado sera alterado.
    exit /b 0
)
if not exist "mqtt\banco.py" (
    call :pendencia "mqtt/banco.py ausente. Restaure o arquivo para criar o banco."
    exit /b 1
)
if not defined PY (
    call :pendencia "Banco nao criado: instale Python e execute novamente este BAT."
    exit /b 1
)
echo Criando banco SQLite...
%PY% "mqtt\banco.py"
if errorlevel 1 goto :banco_falhou
if not exist "dados\saae.db" goto :banco_falhou
%PY% -c "import sqlite3; c=sqlite3.connect('file:dados/saae.db?mode=ro', uri=True); t={r[0] for r in c.execute('SELECT name FROM sqlite_master')}; assert {'estacao_heartbeat','bombacorrego','estadorele','nivelalta','nivelquadrada','sirene','statussirene'}.issubset(t); c.close()"
if errorlevel 1 goto :banco_falhou
echo [OK] Banco SQLite criado e sete tabelas verificadas.
exit /b 0
:banco_falhou
call :pendencia "Falha na criacao ou validacao de dados/saae.db. Confira a saida do terminal. Se um banco parcial foi criado, revise-o antes de executar novamente."
exit /b 1

:configurar_mqtt
echo.
choice /C SN /N /M "Deseja configurar as credenciais MQTT? [S/N]: "
if errorlevel 2 exit /b 0
if not defined PY (
    call :pendencia "Configuracao MQTT indisponivel: instale Python primeiro."
    exit /b 1
)
echo A configuracao substituira mqtt/config.py e config/comandos.php.
%PY% -c "import pathlib, re, os, tempfile; u=input('Usuario Adafruit IO: ').strip(); k=input('AIO Key (senha MQTT): ').strip(); assert re.fullmatch(r'[A-Za-z0-9_-]+',u) and re.fullmatch(r'[A-Za-z0-9_-]+',k), 'Credenciais vazias ou caracteres invalidos'; q=chr(39); nl=chr(10); files=[(pathlib.Path('mqtt/config.py'),'USUARIO = '+repr(u)+nl+'CHAVE = '+repr(k)+nl),(pathlib.Path('config/comandos.php'),'<?php'+nl+nl+'return ['+nl+'    '+q+'usuario'+q+' => '+q+u+q+','+nl+'    '+q+'chave'+q+' => '+q+k+q+','+nl+'];'+nl)]; exec('staged=[]\ntry:\n for p,t in files:\n  p.parent.mkdir(parents=True,exist_ok=True)\n  with tempfile.NamedTemporaryFile(mode='+repr('w')+',encoding='+repr('utf-8')+',dir=p.parent,delete=False) as f:\n   staged.append((pathlib.Path(f.name),p))\n   f.write(t)\n for tmp,p in staged: os.replace(tmp,p)\nfinally:\n for tmp,p in staged: tmp.unlink(missing_ok=True)')"
if errorlevel 1 (
    call :pendencia "Falha ao configurar MQTT. Confira os dois arquivos e execute novamente."
    exit /b 1
)
echo [OK] Credenciais MQTT gravadas nos dois arquivos.
exit /b 0

:detectar_python
set "PY="
for %%P in ("%LocalAppData%\Programs\Python\Python315\python.exe" "%ProgramFiles%\Python315\python.exe") do if exist "%%~P" (
    "%%~P" -c "import sys,struct; assert sys.version_info >= (3,13) and struct.calcsize('P')==8" >nul 2>&1
    if not errorlevel 1 set PY="%%~P"
)
if defined PY exit /b 0
py -3 -c "import sys,struct; assert sys.version_info >= (3,13) and struct.calcsize('P')==8" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY exit /b 0
python -c "import sys,struct; assert sys.version_info >= (3,13) and struct.calcsize('P')==8" >nul 2>&1
if not errorlevel 1 set "PY=python"
exit /b 0

:verificar_vc
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Installed /reg:32 2>nul | findstr /i /c:"0x1" >nul
exit /b %errorlevel%
:preparar_vc
call :verificar_vc
if not errorlevel 1 (echo [OK] Visual C++ x64 detectado & exit /b 0)
call :obter_dependencia VC_redist.x64.zip VC_redist.x64.exe
if errorlevel 1 exit /b 1
echo Instalando Visual C++ x64...
start "" /wait "dependencias\VC_redist.x64.exe" /install /quiet /norestart
if "%errorlevel%"=="3010" call :pendencia "Visual C++ instalado: reinicie o Windows e execute novamente."
call :verificar_vc
if errorlevel 1 (call :pendencia "Visual C++ x64 nao detectado apos instalacao. Execute o instalador local como administrador." & exit /b 1)
echo [OK] Visual C++ x64 detectado
exit /b 0

:verificar_webview
powershell -NoProfile -Command "$roots=@('HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients','HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients','HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients'); $r=foreach($root in $roots){Get-ChildItem $root -ErrorAction SilentlyContinue | Get-ItemProperty -ErrorAction SilentlyContinue | Where-Object {$_.name -like '*WebView2*' -and $_.pv -and $_.pv -ne '0.0.0.0'}}; if($r){exit 0}else{exit 1}"
exit /b %errorlevel%
:preparar_webview
call :verificar_webview
if not errorlevel 1 (echo [OK] WebView2 detectado & exit /b 0)
call :obter_dependencia MicrosoftEdgeWebView2.zip MicrosoftEdgeWebView2.exe
if errorlevel 1 exit /b 1
echo Instalando WebView2...
start "" /wait "dependencias\MicrosoftEdgeWebView2.exe" /silent /install
call :verificar_webview
if errorlevel 1 (call :pendencia "WebView2 nao detectado apos instalacao. Execute o instalador local manualmente." & exit /b 1)
echo [OK] WebView2 detectado
exit /b 0

:criar_atalho
echo.
echo Criando atalho na area de trabalho...
if not exist "C:\SAAE_PAINEL\launcher.pyw" (call :pendencia "Atalho nao criado: C:\SAAE_PAINEL\launcher.pyw ausente." & exit /b 1)
if not exist "C:\SAAE_PAINEL\icone.ico" (call :pendencia "Atalho nao criado: C:\SAAE_PAINEL\icone.ico ausente." & exit /b 1)
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $desktop=[Environment]::GetFolderPath('DesktopDirectory'); if (-not (Test-Path -LiteralPath $desktop -PathType Container)) { throw 'Area de trabalho indisponivel' }; $path=Join-Path $desktop 'SAAE PAINEL.lnk'; $ws=New-Object -ComObject WScript.Shell; $atalho=$ws.CreateShortcut($path); $atalho.TargetPath='C:\SAAE_PAINEL\launcher.pyw'; $atalho.Arguments=''; $atalho.WorkingDirectory='C:\SAAE_PAINEL'; $atalho.IconLocation='C:\SAAE_PAINEL\icone.ico,0'; $atalho.Description='SAAE PAINEL'; $atalho.Save(); if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Atalho nao encontrado' }"
if errorlevel 1 (call :pendencia "Falha ao criar atalho SAAE PAINEL na area de trabalho." & exit /b 1)
echo [OK] Atalho SAAE PAINEL criado ou atualizado.
exit /b 0

:preparar_pasta
if exist "dependencias\" (echo [OK] Pasta dependencias encontrada. & exit /b 0)
mkdir "dependencias"
if not exist "dependencias\" (call :pendencia "Nao foi possivel criar a pasta dependencias." & exit /b 1)
echo [OK] Pasta dependencias criada.
exit /b 0

:preparar_cloudflared
call :obter_dependencia cloudflared.zip cloudflared.exe
if errorlevel 1 exit /b 1
echo [OK] Cloudflared disponivel. Nenhuma instalacao necessaria.
exit /b 0

:obter_dependencia
set "DEP_ZIP=%~1"
set "DEP_EXE=%~2"
set "DEP_URL=https://github.com/samuelrochacarvalho/SAAE_PAINEL/releases/download/dependencias-v1.0/%~1"
if exist "dependencias\%~2" for %%F in ("dependencias\%~2") do if %%~zF GTR 0 (echo [OK] Executavel local: %~2 & exit /b 0)
echo.
echo Preparando %~2...
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $dest=Join-Path (Get-Location).Path 'dependencias'; $zip=Join-Path $dest $env:DEP_ZIP; $partial=$zip+'.part'; $target=Join-Path $dest $env:DEP_EXE; $stage=Join-Path $dest ('extracao_'+[guid]::NewGuid().ToString('N')); try { if(-not (Test-Path -LiteralPath $zip -PathType Leaf)){ $curl=Join-Path $env:SystemRoot 'System32\curl.exe'; if(-not (Test-Path -LiteralPath $curl -PathType Leaf)){throw 'curl.exe nativo indisponivel'}; Write-Host ('Baixando '+$env:DEP_ZIP+' (Total, Received, Speed, Time Left):'); & $curl --disable --location --fail --retry 3 --retry-delay 2 --connect-timeout 30 --continue-at - --output $partial $env:DEP_URL; $rc=$LASTEXITCODE; if($rc -eq 33 -or $rc -eq 36){Write-Host 'Retomada recusada; reiniciando download.'; Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue; & $curl --disable --location --fail --retry 3 --retry-delay 2 --connect-timeout 30 --output $partial $env:DEP_URL; $rc=$LASTEXITCODE}; if($rc -ne 0){throw ('Falha cURL: '+$rc+'; parcial preservado')}; Move-Item -LiteralPath $partial -Destination $zip; Write-Host ('Download concluido: {0:N2} MB' -f ((Get-Item -LiteralPath $zip).Length/1MB)) } else {Write-Host ('Utilizando ZIP local: '+$env:DEP_ZIP)}; Write-Host ('Extraindo '+$env:DEP_ZIP+'...'); Expand-Archive -LiteralPath $zip -DestinationPath $stage; $src=Join-Path $stage $env:DEP_EXE; if(-not (Test-Path -LiteralPath $src -PathType Leaf)){$src=Join-Path (Join-Path $stage 'dependencias') $env:DEP_EXE}; if(-not (Test-Path -LiteralPath $src -PathType Leaf) -or (Get-Item -LiteralPath $src).Length -eq 0){throw 'Executavel ausente ou vazio no ZIP'}; Move-Item -LiteralPath $src -Destination $target -Force; if((Get-Item -LiteralPath $target).Length -eq 0){throw 'Executavel extraido vazio'}; Remove-Item -LiteralPath $zip -Force; if(Test-Path -LiteralPath $partial){Remove-Item -LiteralPath $partial -Force}; Write-Host ('[OK] Executavel preservado: '+$env:DEP_EXE) } catch { Write-Host $_; exit 1 } finally { if(Test-Path -LiteralPath $stage){Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue} }"
if errorlevel 1 (call :pendencia "Falha ao obter %~1. Confira internet, Release e ZIP local. Se o ZIP estiver corrompido, remova-o e tente novamente." & exit /b 1)
exit /b 0

:instalar_python
call :obter_dependencia python-3.15.2-amd64.zip python-3.15.2-amd64.exe
if errorlevel 1 exit /b 1
echo Instalando Python local...
start "" /wait "dependencias\python-3.15.2-amd64.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_tcltk=1 Include_launcher=1
call :detectar_python
if not defined PY exit /b 1
exit /b 0
