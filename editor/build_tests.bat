@echo off
rem Builds and runs the editor's model/codegen tests (needs Visual Studio Build Tools 2022).
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /std:c++17 /EHsc /O1 /MT /W3 /Fo:build\ tests\model_tests.cpp src\model.cpp src\codegen.cpp /Fe:build\model_tests.exe /link d3dcompiler.lib || exit /b 1
build\model_tests.exe
