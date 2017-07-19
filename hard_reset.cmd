pause
pause
pause

type drop_all.sql | call m dbshell
del files\backups\*
del files\recodes\*
del files\uploads\*

rem git diff --name-only release | perl -pe "s#/#\\#g;" | for /f "delims=" %%a in ('findstr migrations\0') do del "%%a"
call m makemigrations games
call m makemigrations core
pause
call m migrate
call m initifdb
call m createsuperuser --email "ersatzplut+bot@gmail.com" --username "бездушный робот" --noinput
call m createsuperuser --email "mooskagh@gmail.com" --username "crem"