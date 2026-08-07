@echo off
REM ---------------------------------------------------------------------------
REM  Gera o executavel Windows (.exe) do "Pacientes Inativos - GestaoDS".
REM
REM  Rode este arquivo em um computador com WINDOWS e Python 3 instalado
REM  (https://www.python.org/downloads/ - marque "Add Python to PATH").
REM
REM  Basta dar um duplo-clique. O .exe aparece na pasta "dist".
REM ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

echo.
echo === Verificando o Python ===
py --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python nao encontrado.
    echo Instale em https://www.python.org/downloads/ e marque "Add Python to PATH".
    echo.
    pause
    exit /b 1
)
py --version

echo.
echo === Instalando o PyInstaller ===
py -m pip install --upgrade pip pyinstaller
if errorlevel 1 (
    echo.
    echo Falha ao instalar o PyInstaller. Verifique sua conexao com a internet.
    echo.
    pause
    exit /b 1
)

echo.
echo === Gerando o executavel ===
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "Pacientes Inativos GestaoDS" ^
    --clean ^
    gestaods_inativos.py
if errorlevel 1 (
    echo.
    echo Falha ao gerar o executavel.
    echo.
    pause
    exit /b 1
)

echo.
echo ===========================================================
echo  Pronto!
echo  O executavel esta em:
echo    %~dp0dist\Pacientes Inativos GestaoDS.exe
echo  Esse arquivo e independente - pode copiar para outro PC.
echo ===========================================================
echo.
pause
