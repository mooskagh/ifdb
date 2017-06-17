pipreqs . --encoding=utf-8 --force --debug 
type requirements.add >> requirements.txt
sort requirements.txt /O reqs.tmp
del requirements.txt
ren reqs.tmp requirements.txt

