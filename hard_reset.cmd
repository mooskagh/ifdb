pause
pause
pause

type drop_all.sql | call m dbshell
del uploads\*
del uploads\recode\*

git diff --name-only release | perl -pe "s#/#\\#g;" | for /f "delims=" %%a in ('findstr migrations\0') do del "%%a"
call m makemigrations games
call m makemigrations core
call m migrate
call m initifdb
call m createsuperuser --email "ersatzplut+bot@gmail.com" --username "бездушный робот" --noinput
call m createsuperuser --email "mooskagh@gmail.com" --username "crem"