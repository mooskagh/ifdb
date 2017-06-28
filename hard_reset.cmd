pause
pause
pause

del db.sqlite3
del games\migrations\0*.py
del core\migrations\0*.py
call m makemigrations games
call m makemigrations core
call m migrate
call m initifdb
call m createsuperuser --email "ersatzplut+bot@gmail.com" --username "бездушный робот" --noinput
call m createsuperuser --email "mooskagh@gmail.com" --username "crem"