from bottle import route, run, template, static_file, get, post, request
from neo4j.v1 import GraphDatabase, basic_auth
from settings import password, username

neo4jDriver = GraphDatabase.driver("bolt:localhost:7687", auth=basic_auth(username, password))

@route('/static/<filename>')
def server_static(filename):
    return static_file(filename, root='static')

@post(/addUser)
def addUser():
    search = request.json
    return dict(items=add_user(search["uName"], search{"password"}))

def add_user(username, password):
    with neo4jDriver.session() as session:
            with session.begin_transaction()as tx:
                tx.run('''
                    CREATE (u:User {ProfileName: {username}, Password: {pswd}),
                    ''',
                    username = uName, pswd = password)
