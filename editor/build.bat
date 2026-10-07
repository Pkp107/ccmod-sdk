@echo off
rem Builds the ccmod transition editor (needs Visual Studio Build Tools 2022). Output: editor\bin\ccmod-transition-editor.exe
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cd /d "%~dp0"
if not exist build mkdir build
if not exist bin mkdir bin
set IM=third_party\imgui
set FLAGS=/nologo /std:c++17 /EHsc /O2 /MT /W3 /DNOMINMAX /DUNICODE /D_UNICODE /I%IM%
rem Dear ImGui is compiled once into a library (delete build\imgui.lib to rebuild it).
if not exist build\imgui.lib (
  cl %FLAGS% /c /Fo:build\ %IM%\imgui.cpp %IM%\imgui_draw.cpp %IM%\imgui_tables.cpp %IM%\imgui_widgets.cpp %IM%\imgui_impl_win32.cpp %IM%\imgui_impl_dx11.cpp || exit /b 1
  lib /nologo /out:build\imgui.lib build\imgui.obj build\imgui_draw.obj build\imgui_tables.obj build\imgui_widgets.obj build\imgui_impl_win32.obj build\imgui_impl_dx11.obj || exit /b 1
)
cl %FLAGS% /Fo:build\ src\main.cpp src\render.cpp src\model.cpp src\codegen.cpp /Fe:bin\ccmod-transition-editor.exe /link /SUBSYSTEM:WINDOWS build\imgui.lib d3d11.lib d3dcompiler.lib dxgi.lib user32.lib gdi32.lib comdlg32.lib ole32.lib windowscodecs.lib shell32.lib dwmapi.lib || exit /b 1
echo Built editor\bin\ccmod-transition-editor.exe
