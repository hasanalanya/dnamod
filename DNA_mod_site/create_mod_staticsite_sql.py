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
import codecs
from itertools import izip
import os
import pybel
import sqlite3
import sys

# Using Jinja2 as templating engine
from jinja2 import Environment
from jinja2 import FileSystemLoader

# permit import from parent directory
sys.path.append(os.path.join(sys.path[0], '..'))
import dnamod_utils

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
CITATION_ORDERED_KEYS_ENCODED = ['pmid', 'title', 'date', 'author']
SEQUENCING_ORDERED_KEYS = ['chebiid', 'pmid', 'author', 'date',
                           'seqtech', 'res', 'enrich']

HTML_FILES_DIR = dnamod_utils.get_constant('site_html_dir')
TEMPLATE_DIR = dnamod_utils.get_constant('site_template_dir')


def render_image(smiles, name):
    FILE_TYPE = 'svg'

    img_dir = dnamod_utils.get_constant('site_image_dir')

    if not os.path.exists(img_dir):
        os.makedirs(img_dir)
    if not smiles:
        return

    svg_path = os.path.join(img_dir, "{}.{}".format(name, FILE_TYPE))

    mol = pybel.readstring('smi', smiles)
    mol.write(FILE_TYPE, svg_path, overwrite=True)


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

        citationList.append(dict(izip(CITATION_ORDERED_KEYS_ENCODED,
                            [item.encode(ENCODING) for item in query])))
    return citationList


def get_table_headers(cursor, table_name):
    c = cursor.cursor()
    c.execute("PRAGMA table_info({})".format(table_name))
    header = [result[1] for result in c.fetchall()]
    return tuple(header)


def get_expanded_alphabet(id, cursor):
    c = cursor.cursor()

    exp_alph_dict = {}

    exp_alph_headers = get_table_headers(cursor, 'expanded_alphabet')

    # seq_headers contains the header for this table
    # overall orders first by date, but still grouped by method
    c.execute('''SELECT DISTINCT nameid,
                 [{2}], [{3}], [{4}], [{5}]
                 FROM expanded_alphabet
                 WHERE nameid = ?
                 '''.format(*exp_alph_headers),
              (id,))
    results = c.fetchall()

    for result in results:
        exp_alph_dict.update(dict(izip(exp_alph_headers, result)))

    return exp_alph_dict


def get_sequencing(id, cursor, seq_headers):
    c = cursor.cursor()
    sequenceList = []

    # seq_headers contains the header for this table
    # overall orders first by date, but still grouped by method
    c.execute('''SELECT DISTINCT seq_c.nameid, ref.citationid,
                     ref.authors, ref.pubdate,
                     seq_c.[{2}], seq_c.[{3}], seq_c.[{4}]
                 FROM sequencing_citations AS seq_c
                 JOIN citations AS ref ON seq_c.[{1}]
                    LIKE '%' || ref.citationid || '%'
                 WHERE nameid = ?
                 ORDER BY COALESCE(seq_c.[{2}],
                                   date(ref.pubdate),
                                   ref.authors, 1)
                 '''.format(*seq_headers),
              (id,))
    results = c.fetchall()

    for row in results:
        sequenceList.append(dict(izip(SEQUENCING_ORDERED_KEYS, row)))
    return sequenceList


def create_html_pages():
    # Load in SQLite database
    conn = sqlite3.connect(dnamod_utils.get_constant('database'))
    c = conn.cursor()

    # Create a Jinja 2 environment object and load in templates
    env = Environment()
    env.loader = FileSystemLoader(TEMPLATE_DIR)

    page_template = env.get_template('modification.html')

    sequencing_headers = get_table_headers(conn, 'sequencing_citations')

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

    if not os.path.exists(HTML_FILES_DIR):
        os.makedirs(HTML_FILES_DIR)

    for BASE in BASES:
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

            # XXX TODO cleanup commented-out code
            # roles_lookup = mod[7] # unused as roles are not on site

            citations = get_citations(citation_lookup, conn)

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

            # Formatting
            formula = formula[1:-1]
            netcharge = netcharge[1:-1]
            iupacname = iupacname[1:-1]
            avgmass = avgmass[1:-1]

            # Write html page
            writefile = HTML_FILES_DIR + chebiname + '.html'
            f = codecs.open(writefile, 'w+', encoding=ENCODING)

            for key in CITATION_ORDERED_KEYS_ENCODED:  # decode encoded values
                for citation in citations:
                    citation[key] = citation[key].decode(ENCODING)

            sequences = get_sequencing(citation_lookup, conn,
                                       sequencing_headers)

            expandedalpha = get_expanded_alphabet(chebiid, conn)

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
                                          SequencingHeader=sequencing_headers,
                                          Sequences=sequences,
                                          # pass ExpandedAlpha=None to disable
                                          ExpandedAlpha=expandedalpha)
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
    env.loader = FileSystemLoader(TEMPLATE_DIR)

    home_template = env.get_template('homepage.html')

    writefile = os.path.join(HTML_FILES_DIR, 'index.html')

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
