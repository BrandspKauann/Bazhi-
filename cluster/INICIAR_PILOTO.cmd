@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title Bazhi - Piloto Docker
py -3 configure.py
if errorlevel 1 goto erro
docker compose config --quiet
if errorlevel 1 goto erro
docker compose up -d --build
if errorlevel 1 goto erro
echo Piloto iniciado em modo SIMULACAO, fila pausada. Nenhum bot antigo foi alterado.
echo Execute o teste conforme LEIA-ME.md antes de migrar dados reais.
pause
exit /b 0
:erro
echo Falha ao iniciar o piloto. Os bots antigos nao foram alterados.
pause
exit /b 1
