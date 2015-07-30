'''
Ankur Jai Sood
09/6/2015

Create_mod_staticsite.py
Function:
1. Opens FSDB database files
2. Returns a modification
3. Creates a html page for the modifcation based on created jinja2 template
4. Creates a home page with links to html modification pages
'''
# Using Jinja2 as templating engine
import csv
import os
import openbabel
import pybel
import sqlite3
from jinja2 import Environment
from jinja2 import FileSystemLoader

# Program Constants
BASES = 'Adenine','Thymine','Cytosine','Guanine','Uracil'
VERIFIED_BASES = 'Adenine','Thymine','Cytosine','Guanine'
UNVERIFIED_BASES = 'UnverifiedAdenine', 'UnverifiedThymine', 'UnverifiedCytosine', 'UnverifiedGuanine', 'UnverifiedUracil' 
BASE_DICT = {'adenine': 'CHEBI:16708','thymine': 'CHEBI:17821','cytosine': 'CHEBI:16040','guanine': 'CHEBI:16235','uracil': 'CHEBI:17568'}
FILE_PATH = os.path.dirname(os.path.abspath(__file__))
FILE_PATH_UP = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..'))

def render_image(smiles, name):
    pwd = FILE_PATH + '/static/images'
    if not os.path.exists(pwd):
        os.makedirs(pwd)
    if not smiles:
        return
    path = pwd + '/' + name + '.svg'
    mol = pybel.readstring('smi', smiles)
    mol.write('svg', path, overwrite=True)


def check_whitelist(molName):
    with open(FILE_PATH + '/static/whitelist/whitelist', 'r') as whitelist:
        reader = csv.reader(whitelist, dialect='excel-tab')
        for line in reader:
            if line == []:
                continue
            if len(line) > 1:
                stringline = line[0]
                stringline = stringline.strip()
                flag = line[1]
                if len(line) > 1:
                    if stringline == molName and flag == '*':
                        return True
        return False


def get_citations(lookup_key, cursor):
    c = cursor.cursor()
    citationList = []
    c.execute("SELECT * FROM citation_lookup WHERE modid = ?", (lookup_key,))
    results = c.fetchall()
    for row in results:
        citation = {}
        citationid = row[1]
        c.execute("SELECT * FROM citations WHERE citationid = ?", (citationid,))
        query = c.fetchone()

        pmid = query[0]
        title = query[1]
        date = query[2]
        author = query[3]

        citation['pmid'] = pmid.encode('ascii', 'ignore')
        citation['title'] = title.encode('ascii', 'ignore')
        citation['date'] = date.encode('ascii', 'ignore')
        citation['author'] = author.encode('ascii', 'ignore')

        citationList.append(citation)
    return citationList


def create_html_pages():
    # Load in SQLite database
    conn = sqlite3.connect(FILE_PATH_UP + '/DNA_mod_database.db')
    c = conn.cursor()

    # Create a Jinja 2 environment object and load in templates
    env = Environment()
    env.loader=FileSystemLoader(FILE_PATH + '/Templates')

    page_template = env.get_template('modification.html')

    # Dictionary to store links for hompage
    homepageLinks = {}
    links = []
    blacklist = []

    c.execute('''DROP TABLE IF EXISTS temp''')
    c.execute("CREATE TABLE temp AS SELECT * FROM (SELECT * from (SELECT * FROM (SELECT * FROM modbase AS MB NATURAL JOIN baseprops) AS MB_BP NATURAL JOIN covmod) AS MB_CV NATURAL JOIN names) AS MB_B NATURAL JOIN base")
    conn.commit()

    for BASE in BASES:
        pwd = FILE_PATH +'/static/'
        if not os.path.exists(pwd):
            os.makedirs(pwd)

        links = []
        blacklist = []

        baseid = BASE[0].lower()
        mods = c.execute("SELECT * FROM temp WHERE baseid = ?", baseid)
        conn.commit()

        for mod in mods:
            # Read data:
            formula = mod[8]
            netcharge = mod[9]
            avgmass = mod[10]
            definition = mod[12]
            chebiname= mod[13].encode('ascii', 'ignore')
            chebiid = mod[14]
            iupacname = mod[15]
            synonyms = mod[16]
            smiles = mod[17].encode('ascii', 'ignore')
            commonname = mod[18]

            citation_lookup = mod[5]
            roles_lookup = mod[7]

            citations = get_citations(citation_lookup, conn)
            #print citations
            #citations = []

            roles = []
            roles_ids = []

            # Process SMILES to render image
            smiles = smiles[1:-1]
            render_image(smiles, chebiname)

            # Process synonyms for list
            synonyms = synonyms[1:-1]
            synonyms = synonyms.split(', ')
            if synonyms == ['']: synonyms = []

            # Write html page
            writefile = pwd + chebiname +'.html'
            f = open(writefile, 'w+')
            render = page_template.render(ChebiName=chebiname, Definition=definition, Formula=formula, NetCharge=netcharge, AverageMass=avgmass, IupacName=iupacname, Smiles=smiles, Synonyms=synonyms, ChebiId=chebiid, CommonName=commonname, Citations = citations, ParentLink = BASE_DICT[commonname], Roles = roles, RolesChebi = roles_ids)
            f.write(render)
            f.close()

            # Check if mod is on whitelist
            link = chebiname
            if check_whitelist(link):
                links.append(link)
            else:
                blacklist.append(link)
        
        links = sorted(links, key=str.lower)
        homepageLinks[BASE] = links
        blacklist = sorted(blacklist, key=str.lower)
        blacklistBase = 'Unverified' + BASE
        homepageLinks[blacklistBase] = blacklist
    return homepageLinks

def create_homepage(homepageLinks):
    verifiedBases = {}
    unverifiedBases = {}
    for base in BASES:
        verifiedBases[base] = homepageLinks[base]
        unvername = 'Unverified' + base
        unverifiedBases[base] = homepageLinks[unvername]

    verifiedBases['Thymine'] = verifiedBases['Thymine'] + verifiedBases['Uracil']
    del(verifiedBases['Uracil'])

    env = Environment()
    env.loader=FileSystemLoader(FILE_PATH + '/Templates')

    home_template = env.get_template('homepage.html')

    writefile = FILE_PATH + '/static/index.html'
    f = open(writefile, 'w+')
    render = home_template.render(bases = VERIFIED_BASES, modifications = verifiedBases, unverifiedbases = BASES, unverifiedmodifications = unverifiedBases)
    f.write(render)
    f.close()


links = create_html_pages()
create_homepage(links)
print "Static Site Generated"
