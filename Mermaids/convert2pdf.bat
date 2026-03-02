@echo off
for %%f in (*.mermaid) do (
    echo Rendering %%f ...
    npx @mermaid-js/mermaid-cli -i "%%f" -o "%%~nf.pdf" -b transparent -f
)
echo Done.
pause
