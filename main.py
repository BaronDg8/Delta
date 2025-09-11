# starts manager.py in main or _internal/main if pyinstaller was used
#

with open("main", "manager.py") as f:
    exec(f.read())


    