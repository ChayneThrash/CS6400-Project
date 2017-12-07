from bottle import route, run, static_file, post, request, app
from neo4j.v1 import GraphDatabase, basic_auth
from settings import password, username
from beaker.middleware import SessionMiddleware
import time, threading


neo4jDriver = GraphDatabase.driver("bolt:localhost:7687", auth=basic_auth(username, password))

@route('/static/<filename>')
def server_static(filename):
    return static_file(filename, root='static')

@post('/search')
def search_beers():
    search = request.json
    total_results = get_search_total(get_user(), search["beerName"], search["breweryName"], search["styles"], search["excludeRated"])
    search_results = get_search_results(get_user(), search["beerName"], search["breweryName"], search["styles"], search["excludeRated"], 10)
    return dict(total=total_results, items=search_results)

@post('/getStyles')
def get_styles():
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            results = tx.run('''
                match   (style:BeerStyle)<-[:HAS_SUBTYPE]-(specific:SpecificStyle)
                return  specific.Style as Specific, style.Style AS Style ORDER BY specific.Style, style.Style''')

            styles = {}
            for record in results:
                specific_style = record["Specific"]
                if not specific_style in styles:
                    styles[specific_style] = []
                styles[specific_style].append(record["Style"])
            return styles

@post('/rate')
def rate():
    rating = request.json["rating"]
    beerId = request.json["beer"]
    addRating(get_user(), beerId, rating)

@post('/login')
def login():
    uname = request.json["username"]
    pwd = request.json["password"]
    return dict(success=user_credentials_are_valid(uname, pwd))

def user_credentials_are_valid(uname, pwd):
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            results = tx.run('''
                match   (u:User {ProfileName: {Username}})
                where   u.password = {Password}
                return  u.ProfileName as Username''', Username=uname, Password=pwd)
            if results is not None:
                result = results.single()
                if result is not None:
                    s = request.environ.get('beaker.session')
                    s['user'] = result["Username"]
                    s.save()
                    return True
            return False

@post('/addUser')
def add_user(username, password):
    search = request.json
    with neo4jDriver.session() as session:
            with session.begin_transaction()as tx:
                tx.run('''
                    CREATE (u:User {ProfileName: {username}, Password: {password}),
                    ''',
                    username = search['uName'], password = search['password')

@post('/recommendations')
def get_recommendations():
    search = request.json
    return dict(items=get_recommendations_for_user(get_user(), search["breweryName"], search["styles"]))

def get_user():
    s = request.environ.get('beaker.session')
    user = s['user']
    return user if user is not None else ""

def get_recommendations_for_user(user, brewery_name, styles):
    brewery_name_regex = ".*(?i)" + brewery_name + ".*"
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            results = tx.run('''
                match   (u:User {ProfileName: {Username}})-[r:REVIEWED]->(b:Beer)-[s:SIMILARITY]-(bSim:Beer),
                        (bSim)-[:IS_STYLE]->(style:BeerStyle)<-[:HAS_SUBTYPE]-(specificStyle:SpecificStyle),
                        (bSim)-[:BREWED_BY]->(brew:Brewery)
                where   brew.Name =~ {BreweryName}
                    AND CASE
                            WHEN size({Styles}) = 0 THEN true
                            ELSE style.Style in {Styles}
                        END
                optional match
                        (bSim)<-[r2:REVIEWED]-(u)
                with    bSim, brew, style, specificStyle, s, r, r2
                where   r2 is null
                with    bSim, brew, style, specificStyle,
                        case
                            when count(s) = 1 then r.Overall*s.similarity
                            else sum(r.Overall*s.similarity)/sum(abs(s.similarity))
                        end as prediction
                return  bSim.Name as BeerName, brew.Name as BreweryName, style.Style as Style, prediction/10 as Predicted
                order by prediction desc
                limit 10''', Username=user, BreweryName=brewery_name_regex, Styles=styles)
            formatted_results = []
            for record in results:
                formatted_result = dict(beer=record["BeerName"], brewery=record["BreweryName"],
                                        style=record["Style"], predicted=record["Predicted"])
                formatted_results.append(formatted_result)
            return formatted_results

def addRating(user, beerId, rating):
    overall = int(rating["overall"] * 10)
    palate = int(rating["palate"] * 10)
    taste = int(rating["taste"] * 10)
    aroma = int(rating["aroma"] * 10)
    appearance = int(rating["appearance"] * 10)
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            tx.run('''
                MATCH   (u:User {ProfileName: {Username}}), (b:Beer {Id: {BeerId}})
                MERGE   (u)-[r:REVIEWED]->(b)
                SET     r.Overall = {Overall}
                SET     r.Palate = {Palate}
                SET     r.Taste = {Taste}
                SET     r.Appearance = {Appearance}
                SET     r.Aroma = {Aroma}
                MERGE  (review:QueuedReview {ProfileName: {Username}, BeerId: {BeerId}})
                SET     review.QueuedAt = timestamp()''',
                             Username=user, BeerId=beerId, Overall=overall, Palate=palate, Taste=taste,
                             Aroma=aroma, Appearance=appearance)

def get_search_total(user, beer_name, brewery_name, styles, exclude_rated):
    brewery_name_regex = ".*(?i)" + brewery_name + ".*"
    beer_name_regex = ".*(?i)" + beer_name + ".*"
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            results = tx.run('''
                    match   (brewery:Brewery)<-[:BREWED_BY]-(beer:Beer)-[:IS_STYLE]->(style:BeerStyle)
                    where   brewery.Name =~ {BreweryName}
                        AND beer.Name =~ {BeerName}
                        AND CASE
                                WHEN size({Styles}) = 0 THEN true
                                ELSE style.Style in {Styles}
                            END
                    optional match (u:User {ProfileName: {Username}})-[r:REVIEWED]->(beer)
                    WITH    beer, r
                    WHERE   NOT {ExcludeRated} OR r is null
                    return  count(distinct beer) as TotalBeers''',
                             Username=user, BreweryName=brewery_name_regex, BeerName=beer_name_regex, Styles=styles,
                             ExcludeRated=exclude_rated)

            return results.single()["TotalBeers"]

def get_search_results(user, beer_name, brewery_name, styles, exclude_rated, result_count):
    brewery_name_regex = ".*(?i)" +brewery_name + ".*"
    beer_name_regex = ".*(?i)" + beer_name + ".*"
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            results = tx.run('''
                match   (brewery:Brewery)<-[:BREWED_BY]-(beer:Beer)-[:IS_STYLE]->(style:BeerStyle)
                where   brewery.Name =~ {BreweryName}
                    AND beer.Name =~ {BeerName}
                    AND CASE
                            WHEN size({Styles}) = 0 THEN true
                            ELSE style.Style in {Styles}
                        END
                optional match (u:User {ProfileName: {Username}})-[r:REVIEWED]->(beer)
                WITH    brewery, beer, style, r
                WHERE   NOT {ExcludeRated} OR r is null
                WITH    brewery, beer, style,
                        CASE
                            WHEN r is null THEN -1
                            ELSE r.Overall
                        END as rating
                return  brewery.Name AS Brewery, beer.Id AS BeerId, beer.Name AS Beer, style.Style AS Style, toFloat(rating)/10.0 AS rating
                ORDER BY brewery.Name, beer.Name, style.Style LIMIT 10''',
                             Username = user, BreweryName=brewery_name_regex, BeerName=beer_name_regex, Styles=styles,
                             ExcludeRated=exclude_rated)

            formatted_results = []
            for record in results:
                formatted_result = dict(brewery=record["Brewery"], beer=record["Beer"], style=record["Style"],
                                        rating=record["rating"], beerId=record["BeerId"])
                formatted_results.append(formatted_result)
            return formatted_results


def update_model_with_queued_reviews():
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            tx.run('''
                match   (q:QueuedReview)
                with    q order by q.QueuedAt asc limit 1
                match   (b:Beer {Id: q.BeerId})<-[r1:REVIEWED]-(u:User)-[r2:REVIEWED]->(b2:Beer)
                where   b <> b2
                match   (b2)<-[:REVIEWED]-(u2:User {ProfileName: q.ProfileName})
                optional match (u)-[ur:REVIEWED]->()
                with    b, b2, r1, r2, q, u,
                        avg(ur.Overall) as ao, avg(ur.Palate) as ap,
                        avg(ur.Aroma) as aar, avg(ur.Appearance) as aap,
                        avg(ur.Taste) as at
                with    b, b2, q,
                        sum((r1.Overall - ao)*(r2.Overall - ao)) as dotproduct,
                        sqrt(sum((r1.Overall - ao)^2)) * sqrt(sum((r2.Overall - ao)^2)) as bottomHalf,
                        sum((r1.Aroma - aar)* (r2.Aroma - aar)) as dotproductAroma,
                        sqrt(sum((r1.Aroma - aar)^2)) * sqrt(sum((r2.Aroma - aar)^2)) as bottomHalfAroma,
                        sum((r1.Appearance - aap) * (r2.Appearance - aap)) as dotproductAppearance,
                        sqrt(sum((r1.Appearance - aap)^2)) * sqrt(sum((r2.Appearance - aap)^2)) as bottomHalfAppearance,
                        sum((r1.Palate - ap) * (r2.Palate - ap)) as dotproductPalate,
                        sqrt(sum((r1.Palate - ap)^2)) * sqrt(sum((r2.Palate - ap)^2)) as bottomHalfPalate,
                        sum((r1.Taste - at) * (r2.Taste - at)) as dotproductTaste,
                        sqrt(sum((r1.Taste - at)^2)) * sqrt(sum((r2.Taste - at)^2)) as bottomHalfTaste,
                        count(u) as userCount
                where   userCount > 1
                with    b, b2, q,
                        case when dotproduct = 0 then 0 else dotproduct/bottomHalf end as overallSim,
                        case when dotproductAroma = 0 then 0 else dotproductAroma/bottomHalfAroma end as aromaSim,
                        case when dotproductAppearance = 0 then 0 else dotproductAppearance/bottomHalfAppearance end as appearanceSim,
                        case when dotproductPalate = 0 then 0 else dotproductPalate/bottomHalfPalate end as palateSim,
                        case when dotproductTaste = 0 then 0 else dotproductTaste/bottomHalfTaste end as tasteSim
                with    b, b2, (overallSim + aromaSim + appearanceSim + palateSim + tasteSim)/5 as similarity, q
                MERGE   (b)-[s:SIMILARITY]-(b2)
                SET     s.similarity = similarity
                DELETE  q
                ''')

def run_update_model():
    while True:
        update_model_with_queued_reviews()
        time.sleep(10)

update_thread = threading.Thread(target=run_update_model)
update_thread.start()


session_opts = {
    'session.type': 'file',
    'session.cookie_expires': 300,
    'session.data_dir': './data',
    'session.auto': True
}
app = SessionMiddleware(app(), session_opts)

run(app=app, host='localhost', port=8080)
