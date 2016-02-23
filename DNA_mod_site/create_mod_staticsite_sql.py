#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import with_statement, division, print_function

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
import csv
import codecs
import itertools
import os
import pybel
import sqlite3
import sys
# Using Jinja2 as templating engine
from jinja2 import Environment
from jinja2 import FileSystemLoader

# Program Constants
ENCODING = 'utf8'
BASES = 'Adenine', 'Cytosine', 'Guanine', 'Thymine', 'Uracil'
VERIFIED_BASES = 'Adenine', 'Cytosine', 'Guanine', 'Thymine'
UNVERIFIED_BASES = ('UnverifiedAdenine', 'UnverifiedThymine',
                    'UnverifiedCytosine', 'UnverifiedGuanine',
                    'UnverifiedUracil')
BASE_DICT = {'adenine': 'CHEBI:16708', 'thymine': 'CHEBI:17821',
             'cytosine': 'CHEBI:16040', 'guanine': 'CHEBI:16235',
             'uracil': 'CHEBI:17568'}
FILE_PATH = os.path.dirname(os.path.abspath(__file__))
FILE_PATH_UP = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CITATION_ORDERED_KEYS_ENCODED = ['pmid', 'title', 'date', 'author']
SEQUENCING_ORDERED_KEYS = ['chebiid', 'pmid', 'seqtech', 'res', 'enrich']

# Import custom functions from dnamod_utils.py
sys.path.insert(0, FILE_PATH_UP)
import dnamod_utils


def render_image(smiles, name):
    pwd = FILE_PATH + '/static/images'
    if not os.path.exists(pwd):
        os.makedirs(pwd)
    if not smiles:
        return
    path = pwd + '/' + name + '.svg'
    mol = pybel.readstring('smi', smiles)
    mol.write('svg', path, overwrite=True)


def get_citations(lookup_key, cursor):
    c = cursor.cursor()
    citationList = []
    c.execute("SELECT * FROM citation_lookup WHERE nameid = ?", (lookup_key,))
    results = c.fetchall()
    for row in results:
        citationid = row[1]
        c.execute("SELECT * FROM citations WHERE citationid = ?",
                  (citationid,))
        query = c.fetchone()

        citationList.append(dict(itertools.izip(CITATION_ORDERED_KEYS_ENCODED,
                            [item.encode(ENCODING) for item in query])))
    return citationList


def get_sequencing(id, cursor):
    c = cursor.cursor()
    sequenceList = []
    c.execute("SELECT * from sequencing_citations WHERE nameid = ?", (id,))
    results = c.fetchall()
    for row in results:
        sequenceList.append(dict(itertools.izip(SEQUENCING_ORDERED_KEYS, row)))
    return sequenceList

    
def create_html_pages():
    # Load in SQLite database
    conn = sqlite3.connect(FILE_PATH_UP + '/DNA_mod_database.db')
    c = conn.cursor()

    # Create a Jinja 2 environment object and load in templates
    env = Environment()
    env.loader = FileSystemLoader(FILE_PATH + '/Templates')

    page_template = env.get_template('modification.html')

    # Dictionary to store links for hompage
    homepageLinks = {}
    links = []
    blacklist = []

    c.execute('''DROP TABLE IF EXISTS temp''')
    c.execute('''CREATE TABLE temp AS SELECT * FROM
                    (SELECT * from
                        (SELECT * FROM
                            (SELECT * FROM modbase
                             AS MB NATURAL JOIN baseprops)
                        AS MB_BP NATURAL JOIN covmod)
                    AS MB_CV NATURAL JOIN names)
                AS MB_B NATURAL JOIN base''')
    conn.commit()

    for BASE in BASES:
        pwd = FILE_PATH + '/static/'
        if not os.path.exists(pwd):
            os.makedirs(pwd)

        links = []
        blacklist = []

        baseid = BASE[0].lower()
        mods = c.execute("SELECT * FROM temp WHERE baseid = ?", baseid)
        conn.commit()

        for mod in mods:
            # Read data:
            formula = mod[3]
            netcharge = mod[8]
            avgmass = mod[6]
            definition = mod[9]
            chebiname = mod[10].encode('ascii')
            chebiid = mod[0]
            iupacname = mod[11]
            synonyms = mod[12]
            smiles = mod[13].encode('ascii')
            commonname = mod[14]

            citation_lookup = mod[0]
            # roles_lookup = mod[7] # unused as roles are not on site

            citations = get_citations(citation_lookup, conn)
            # print citations
            # citations = []

            roles = []
            roles_ids = []

            print("Creating page: " + chebiname + ".html")
            # Process SMILES to render image
            smiles = smiles[1:-1]
            render_image(smiles, chebiname)

            # Process synonyms for list
            synonyms = synonyms[1:-1]
            synonyms = synonyms.split(', ')
            if synonyms == ['']:
                synonyms = []
            result = []
            for name in synonyms:
                name = name[1:-1]
                result.append(name)
            synonyms = result

            smiles = smiles.decode('ascii')
            chebiname = chebiname.decode('ascii')

            # Write html page
            writefile = pwd + chebiname + '.html'
            f = codecs.open(writefile, 'w+', encoding=ENCODING)

            for key in CITATION_ORDERED_KEYS_ENCODED:  # decode encoded values
                for citation in citations:
                    citation[key] = citation[key].decode(ENCODING)

            sequences = get_sequencing(citation_lookup, conn)
            
            render = page_template.render(ChebiName=chebiname,
                                          Definition=definition,
                                          Formula=formula,
                                          NetCharge=netcharge,
                                          AverageMass=avgmass,
                                          IupacName=iupacname,
                                          Smiles=smiles,
                                          Synonyms=synonyms,
                                          ChebiId=chebiid,
                                          CommonName=commonname,
                                          Citations=citations,
                                          ParentLink=BASE_DICT[commonname],
                                          Roles=roles,
                                          RolesChebi=roles_ids,
                                          Sequences=sequences)
            f.write(render)
            f.close()

            # Check if mod is on whitelist
            link = chebiname
            if mod[5]:
                links.append(link)
            else:
                blacklist.append(link)

        links = sorted(links, key=lambda s: s.lower())
        homepageLinks[BASE] = links
        blacklist = sorted(blacklist, key=lambda s: s.lower())
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

    verifiedBases['Thymine'] = (verifiedBases['Thymine'] +
                                verifiedBases['Uracil'])
    del(verifiedBases['Uracil'])

    env = Environment()
    env.loader = FileSystemLoader(FILE_PATH + '/Templates')

    home_template = env.get_template('homepage.html')

    writefile = FILE_PATH + '/static/index.html'
    f = codecs.open(writefile, 'w+', encoding=ENCODING)

    render = home_template.render(bases=VERIFIED_BASES,
                                  modifications=verifiedBases,
                                  unverifiedbases=BASES,
                                  unverifiedmodifications=unverifiedBases)
    f.write(render)
    f.close()

print("Generating Static Site....")
links = create_html_pages()
create_homepage(links)
print("Static Site Generated")