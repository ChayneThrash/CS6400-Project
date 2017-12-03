from bottle import route, run, template, static_file, get, post, request
from neo4j.v1 import GraphDatabase, basic_auth
from settings import password, username

neo4jDriver = GraphDatabase.driver("bolt:localhost:7687", auth=basic_auth(username, password))

@route('/static/<filename>')
def server_static(filename):
    return static_file(filename, root='static')

@post('/search')
def search_beers():
    search = request.json
    total_results = get_search_total("cthrash", search["beerName"], search["breweryName"], search["styles"], search["excludeRated"])
    search_results = get_search_results("cthrash", search["beerName"], search["breweryName"], search["styles"], search["excludeRated"], 10)
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
    addRating("cthrash", beerId, rating)

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
                SET     r.Aroma = {Aroma}''',
                             Username=user, BeerId=beerId, Overall=overall, Palate=palate, Taste=taste,
                             Aroma=aroma, Appearance=appearance)

def get_search_total(user, beer_name, brewery_name, styles, exclude_rated):
    brewery_name_regex = ".*(?i)" + brewery_name + ".*"
    beer_name_regex = ".*(?i)" + beer_name + ".*"
    with neo4jDriver.session() as session:
        with session.begin_transaction() as tx:
            results = tx.run(''' 
                    match   (u:User {ProfileName: {Username}})-[r:REVIEWED]->(b:Beer)
                    with    collect({overallScore: r.Overall, beer: b}) as reviewSummary
                    match   (brewery:Brewery)<-[:BREWED_BY]-(beer:Beer)-[:IS_STYLE]->(style:BeerStyle)
                    where   brewery.Name =~ {BreweryName} 
                        AND beer.Name =~ {BeerName} 
                        AND CASE 
                                WHEN size({Styles}) = 0 THEN true 
                                ELSE style.Style in {Styles}
                            END
                    WITH    beer, filter(x IN reviewSummary WHERE x.beer = beer) as beerReview
                    WHERE   NOT {ExcludeRated} OR size(beerReview) = 0
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
                match   (u:User {ProfileName: {Username}})-[r:REVIEWED]->(b:Beer)
                with    collect({overallScore: r.Overall, beer: b}) as reviewSummary
                match   (brewery:Brewery)<-[:BREWED_BY]-(beer:Beer)-[:IS_STYLE]->(style:BeerStyle)
                where   brewery.Name =~ {BreweryName} 
                    AND beer.Name =~ {BeerName} 
                    AND CASE 
                            WHEN size({Styles}) = 0 THEN true 
                            ELSE style.Style in {Styles}
                        END
                WITH    brewery, beer, style, filter(x IN reviewSummary WHERE x.beer = beer) as beerReview
                WHERE   NOT {ExcludeRated} OR size(beerReview) = 0
                WITH    brewery, beer, style, 
                        CASE 
                            WHEN size(beerReview) = 0 THEN -1 
                            ELSE head(beerReview).overallScore 
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




run(host='localhost', port=8080)