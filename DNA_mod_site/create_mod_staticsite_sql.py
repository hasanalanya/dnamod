#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import with_statement, division, print_function

"""Creates the DNAmod website.

-------------------------------------------------------------------------------
Copyright (C) 2016  Ankur Jai Sood and Coby Viner

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
-------------------------------------------------------------------------------
"""

import atexit
import codecs
from collections import OrderedDict, defaultdict, MutableSequence
from copy import deepcopy
from itertools import izip
import os
import pybel
from pysqlite2 import dbapi2 as sqlite3  # needed for latest SQLite
import sys
import os.path
import datetime
import re
import shutil

# Using Jinja2 as templating engine
import jinja2

# permit import from parent directory
sys.path.append(os.path.join(sys.path[0], '..'))
import dnamod_utils

# Program Constants
ENCODING = 'utf8'

JINJA2_EXTENSION_NAMES = ['do']
JINJA2_EXTENSIONS = ['jinja2.ext.' + ext_name for ext_name
                     in JINJA2_EXTENSION_NAMES]

BASES = 'Adenine', 'Cytosine', 'Guanine', 'Thymine', 'Uracil', 'Other'
VERIFIED_BASES = 'Adenine', 'Cytosine', 'Guanine', 'Thymine', 'Other'
UNVERIFIED_BASES = ('UnverifiedAdenine', 'UnverifiedThymine',
                    'UnverifiedCytosine', 'UnverifiedGuanine',
                    'UnverifiedUracil')
BASE_DICT = {'adenine': 'CHEBI:16708', 'thymine': 'CHEBI:17821',
             'cytosine': 'CHEBI:16040', 'guanine': 'CHEBI:16235',
             'uracil': 'CHEBI:17568', 'other': ''}
REF_COL_NAMES = ['citationid', 'title', 'pubdate', 'authors',
                 'journalname', 'volume', 'issue']

HTML_FILES_DIR = dnamod_utils.get_constant('site_html_dir')
TEMPLATE_DIR = dnamod_utils.get_constant('site_template_dir')
DATABASE_FILE_FULLPATH = dnamod_utils.get_constant('database')
DATABASE_FILE_COPY = dnamod_utils.get_constant('database_copy')
SEQ_ANNOT_TABLE = dnamod_utils.get_constant('seq_annot_table')
NATURE_ANNOT_TABLE = dnamod_utils.get_constant('nature_annot_table')
REFERENCES_TABLE = dnamod_utils.get_constant('references_table')

DNAMOD_VERSION = dnamod_utils.get_constant('dnamod_version')
CHEBI_VERSION = dnamod_utils.get_constant('chebi_version')

IMAGE_FORMAT = 'svg'
OTHER_RATIO = 8
OTHER_SHARED_BASE = 'thymine'

# shade these types of origins (or any containing the type as a word)
# in the homepage pie menu display
SHADE_ORIGINS = ['synthetic']

# Create Database copy file to work with in script
shutil.copy2(DATABASE_FILE_FULLPATH, DATABASE_FILE_COPY)


def _exit_handler():
    try:
        os.remove(DATABASE_FILE_COPY)
    except OSError:
        pass


atexit.register(_exit_handler)


def is_list(object):
    """Test if the given object is a list, by checking if
       it is an instance of its proximal abstract class."""
    return isinstance(object, MutableSequence)


def render_image(smiles, name):
    """Creates images of chemical structures from their SMILES, with PyBel.
       The SVG image is saved. The relative path of the image is returned,
       if it exists. Otherwise, None is returned.
    """

    image_dir = dnamod_utils.get_constant('site_image_dir')

    if not os.path.exists(image_dir):
        os.makedirs(image_dir)
    if not smiles:
        return

    image_path = os.path.join(image_dir,
                              "{}.{}".format(name, IMAGE_FORMAT))

    mol = pybel.readstring('smi', smiles)
    mol.write(IMAGE_FORMAT, image_path, overwrite=True)

    if not os.path.isfile(image_path):
        print("Warning: failed to render image"
              "for {}".format(name), file=sys.stderr)
        image_path = None

    # return the relative path, from the site HTML directory
    image_relpath = os.path.relpath(image_path, HTML_FILES_DIR)

    return image_relpath


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

        if not query:  # allow empty citations
            continue

        citationList.append(dict(izip(REF_COL_NAMES,
                            [item for item in query])))
        citationList.sort(key=lambda x: x['authors'])
    return citationList


def get_table_headers(cursor, table_name):
    c = cursor.cursor()
    c.execute("PRAGMA table_info({})".format(table_name))
    header = [result[1] for result in c.fetchall()]
    return list(header)


def get_expanded_alphabet(id, cursor):
    c = cursor.cursor()

    exp_alph_dict = {}

    exp_alph_headers = get_table_headers(cursor, 'expanded_alphabet')

    # TODO refactor to dynamically select columns from header length
    # seq_headers contains the header for this table
    # overall orders first by date, but still grouped by method
    c.execute('''SELECT DISTINCT nameid,
                 [{1}], [{2}], [{3}], [{4}], [{5}]
                 FROM expanded_alphabet
                 WHERE nameid = ?
                 '''.format(*exp_alph_headers),
              (id,))
    results = c.fetchall()

    for result in results:
        exp_alph_dict.update(dict(izip(exp_alph_headers, result)))

    return exp_alph_dict


def get_mod_base_ref_annot_data(id, cursor, table):
    """Get data for mod. base annotations with references.

    Keyword arguments:
    id -- the entries ChEBI ID
    cursor -- the SQLite cursor
    table -- the table containing the annotations

    Returns:
    A list of ordered dictionaries, containing the headers
    as keys and their content as values. Each list element
    pertains to an entry for the current id (i.e. one row).
    """

    c = cursor.cursor()

    annot_dict_list = []

    table_header = get_table_headers(cursor, table)

    # use all columns except first (id) and last (ref.)
    table_header.pop(0)
    reference_col_name = table_header.pop(-1)

    subquery_alias = 'modbase_refs_ord'

    sel_cols_str = ''
    for num, col in enumerate(table_header, 1):
        sel_cols_str += "{}.[{}]".format(subquery_alias, col)

        if num < len(table_header):
            sel_cols_str += ", "
        else:
            break

    # Overall orders first by reference's date,
    # both within groups and to determine group order,
    # but still grouped by the second column of data.

    c.execute('''SELECT DISTINCT
                     GROUP_CONCAT({5}.citationid, ';'),
                     GROUP_CONCAT({5}.title, ';'),
                     GROUP_CONCAT({5}.pubdate, ';'),
                     GROUP_CONCAT({5}.authors, ';'),
                     GROUP_CONCAT({5}.journalnameorpublishername, ';'),
                     GROUP_CONCAT({5}.volumeorpublisherlocation, ';'),
                     GROUP_CONCAT({5}.issue, ';'),
                     {2}
                 FROM (
                        SELECT * FROM {0}
                        JOIN {1} AS ref ON {0}.[{3}]
                            LIKE '%' || ref.citationid || '%'
                        WHERE nameid = ?
                        ORDER BY COALESCE(date(ref.pubdate),
                                         ref.authors, 1)
                 ) {5}
                 GROUP BY {2}
                 ORDER BY COALESCE({5}.[{4}],
                                   date({5}.pubdate),
                                   {5}.authors, 1)
                 '''.format(table, REFERENCES_TABLE, sel_cols_str,
                            reference_col_name, table_header[0],
                            subquery_alias), (id,))

    results = c.fetchall()

    for result in results:
        annot_dict_list += [OrderedDict(izip(REF_COL_NAMES +
                                        table_header, result))]

    if results == []:
        c.execute('''SELECT * FROM {0} WHERE nameid = ?'''.format(table),
                  (id,))
        results = c.fetchall()

        for result in results:
            result = list(result)
            result.pop(0)
            annot_dict_list += [OrderedDict(izip(table_header, result))]

    return annot_dict_list


def create_html_pages(env):
    """Loads data for all modification pages and creates them.
       Returns a tuple of dictionaries: one containing links to
       the pages and another, keyed by ChEBI ID specifying the origin
       of each base, for only the verified modified nucleobases."""

    page_template = env.get_template('modification.html')

    # Dictionary to store links for hompage
    homepage_links = {}
    links = []
    blacklist = []

    # dictionary, keyed by ChEBI ID, storing verified base origins
    v_base_origins = {}

    # load in the SQLite database, storing it purely in memory
    conn = sqlite3.connect(':memory:')
    c = conn.cursor()

    command = "ATTACH DATABASE '{}' as db".format(DATABASE_FILE_COPY)
    c.execute(command)

    c.execute('''CREATE TEMP TABLE temp AS SELECT * FROM
                    (SELECT * FROM
                        (SELECT * FROM
                            (SELECT * FROM db.modbase
                             AS MB NATURAL JOIN db.baseprops)
                        AS MB_BP NATURAL JOIN db.covmod)
                    AS MB_CV NATURAL JOIN db.names)
                AS MB_B NATURAL JOIN db.base''')
    conn.commit()

    if not os.path.exists(HTML_FILES_DIR):
        os.makedirs(HTML_FILES_DIR)

    for BASE in BASES:
        links = []
        blacklist = []

        baseid = BASE[0]
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
            inchi = mod[14]
            inchikey = mod[15]
            commonname = mod[16]

            citations = get_citations(chebiid, conn)

            roles = []
            roles_ids = []

            print("Creating page: " + chebiname + ".html")
            # Process SMILES to render image
            smiles = smiles[1:-1]

            image_path = render_image(smiles, chebiname)

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
            chebiname_title = formatCuratedName(chebiname)

            # Formatting
            formula = formula[1:-1]
            netcharge = netcharge[1:-1]
            iupacname = iupacname[1:-1]
            avgmass = avgmass[1:-1]
            inchi = inchi[1:-1]
            inchikey = inchikey[1:-1]

            # Write html page
            writefile = os.path.join(HTML_FILES_DIR, chebiname + '.html')
            f = codecs.open(writefile, 'w+', encoding=ENCODING)

            for key in REF_COL_NAMES:  # decode encoded values
                for citation in citations:
                    citation[key] = citation[key]

            seq_annot = get_mod_base_ref_annot_data(chebiid, conn,
                                                    SEQ_ANNOT_TABLE)

            nature_annot = get_mod_base_ref_annot_data(chebiid, conn,
                                                       NATURE_ANNOT_TABLE)

            synthetic = False
            if nature_annot:
                # at most a single entry per base for this
                # problem here with empty lists
                # assert len(nature_annot) == 1

                v_base_origins[chebiid] = nature_annot[0]['Origin']
                if v_base_origins[chebiid][0] == "s":
                    synthetic = True

            ref_annot_tab_names = ['Mapping techniques', 'Nature']

            ref_annots = [seq_annot, nature_annot]

            expanded_alpha = get_expanded_alphabet(chebiid, conn)
            if expanded_alpha:
                expanded_alpha["Name"] = \
                    formatCuratedName(expanded_alpha["Name"])

            # record the last modified date (UTC) without the time
            # the resulting datetime object will print in ISO 8601 format
            last_mod_time = os.path.getmtime(DATABASE_FILE_FULLPATH)
            last_mod_dt = datetime.datetime.utcfromtimestamp(last_mod_time).date()
    
            render = page_template.render(ChebiName=chebiname_title,
                                          Definition=definition,
                                          Formula=formula,
                                          NetCharge=netcharge,
                                          AverageMass=avgmass,
                                          IupacName=iupacname,
                                          Smiles=smiles,
                                          InChI=inchi,
                                          InChIKey=inchikey,
                                          Synonyms=synonyms,
                                          ChebiId=chebiid,
                                          CommonName=commonname,
                                          Image=image_path,
                                          Citations=citations,
                                          ParentLink=BASE_DICT[commonname],
                                          Roles=roles,
                                          RolesChebi=roles_ids,
                                          RefAnnotTabNames=ref_annot_tab_names,
                                          RefAnnots=ref_annots,
                                          RefAnnotsRefColNames=REF_COL_NAMES,
                                          # pass ExpandedAlpha=None to disable
                                          ExpandedAlpha=expanded_alpha,
                                          Synthetic=synthetic,
                                          time=last_mod_dt,
                                          DnamodVer=DNAMOD_VERSION,
                                          ChebiVer=CHEBI_VERSION)

            f.write(render)
            f.close()

            # Check if mod is on whitelist
            link = chebiname
            if mod[5]:
                links.append(link)
            else:
                blacklist.append(link)

        links = sorted(links, key=lambda s: s.lower())
        homepage_links[BASE] = links
        blacklist = sorted(blacklist, key=lambda s: s.lower())
        blacklistBase = 'Unverified' + BASE
        homepage_links[blacklistBase] = blacklist

    return (homepage_links, v_base_origins)


def get_modbase_hierarchy(cursor, base_id):
    """ Recursively find all verified modified base child
        ChEBI IDs for the provided modified base ChEBI ID.
        Output is ordered by increasing depth.
    """
    # use a recursive common table expression to get all children
    # and then group these by their root base, creating a hierarchy,
    # ordered by descending depth within the ontology.
    hierarchy = cursor.execute("""WITH hierarchy AS (
                                     -- Rec. Q to find children ad infinitum
                                     WITH RECURSIVE base_children AS (
                                         SELECT nameid, parentid,
                                             '' AS prevpar, 0 AS depth
                                         FROM modbase_parents
                                         WHERE parentid=:bID
                                         UNION ALL
                                         -- The second parentid is used to
                                         -- recursively record previous parents
                                         -- The depth in the tree is also rec.
                                         SELECT b.nameid, b.parentid,
                                             b.parentid, depth + 1
                                         FROM modbase_parents AS b
                                         JOIN base_children modbase_parents ON
                                             b.parentid=modbase_parents.nameid
                                     )
                                     SELECT depth, prevpar, nameid
                                     FROM base_children
                                     -- Could add below WHERE to remove
                                     -- those at depth 0, but want these
                                     -- WHERE parentid <> :bID
                                ) SELECT prevpar, GROUP_CONCAT(nameid)
                                  FROM hierarchy
                                  -- Could add below WHERE to remove seen items
                                  -- WHERE nameid
                                  --     NOT IN (select prevpar FROM hierarchy)
                                  --
                                  -- Only select verified bases
                                  WHERE nameid IN
                                      (select nameid FROM modbase
                                       WHERE verifiedstatus=1)
                                  GROUP BY prevpar
                                  ORDER BY depth DESC
                             """, {"bID": base_id})

    return [list(result) for result in hierarchy.fetchall()]


def cons_nested_verified_dict_modbase_hierarchy(conn, cursor):
    """Returns a dictionary, keyed by the hierarchy depth,
       of the hierarchy of verified modified bases, as values,
       containing nested lists."""
    # NB: this is a highly inefficient way of doing things, from
    # the non-batch insertions and deletions to the lack of SQL
    # query optimization. This only applies, however, for a
    # small subset of bases (those that are verified), which is
    # always going to be a fairly small set.

    # get all root verified bases (i.e. those without parents)
    # since we will be recursively computing their children,
    # referring to unmodified bases by their full name
    verified_root_base_IDs_Q = cursor.execute("""SELECT DISTINCT commonname, nameid
                                                 FROM modbase AS mod
                                                 JOIN base AS unmod
                                                     ON mod.baseid=unmod.baseid
                                                 WHERE verifiedstatus=1
                                                     AND nameid NOT IN
                                                     -- s.t. it has no
                                                     -- *verified* parents
                                                     -- (since those are added
                                                     --  at the next level).
                                                     -- May have unverified
                                                     -- parents, which we
                                                     -- want to add, without
                                                     -- some unverified
                                                     -- intermediate like 6hmA.
                                                    (SELECT mod.nameid FROM
                                                     modbase_parents AS par
                                                     JOIN modbase AS mod
                                                     ON par.nameid=mod.nameid
                                                     WHERE
                                                         (SELECT verifiedstatus
                                                          FROM modbase
                                                          WHERE nameid=
                                                          par.parentid)
                                                         =1)
                                                 ORDER BY commonname""")

    verified_root_base_IDs_by_unmod_base = defaultdict(list)
    for unmod_key, result in verified_root_base_IDs_Q.fetchall():
        unmod_key = str(unmod_key)  # no need for Unicode

        # uracil -> thymine, since verified
        if 'uracil' in unmod_key.lower():
            unmod_key = 'thymine'

        assert unmod_key[:1].upper() in dnamod_utils.UNMOD_ALPH

        verified_root_base_IDs_by_unmod_base[unmod_key].append(result)

    # NB: all children of verified bases are also verified, so we
    #     do not check this
    verified_full_hierarchy_dict = defaultdict(list)
    seen_children = {}

    for (unmod_parent,
         mod_base_children) in (verified_root_base_IDs_by_unmod_base.
                                iteritems()):
        for mod_base in mod_base_children:
            #  INSERT INTO modbase_parents VALUES(mod_base, unmod_parent)
            #  then query for unmod_parent and not mod_base...
            cursor.execute("""INSERT INTO modbase_parents
                              VALUES(?, ?)""", (mod_base, unmod_parent))
            conn.commit()

            hier_query_base = unmod_parent
            modbase_hierarchy = get_modbase_hierarchy(cursor, hier_query_base,)

            cursor.execute("""DELETE FROM modbase_parents
                              WHERE nameid=? AND parentid=?""",
                           (mod_base, unmod_parent))
            conn.commit()

            for relation_idx, modbase_relation in enumerate(modbase_hierarchy):
                parent = modbase_relation[0]

                # children
                modbase_relation[1] = [id for id in
                                       modbase_relation[1].split(',')]

                # create a valid nesting by embedding previous
                # children within their later referring element
                for idx, child in enumerate(modbase_relation[1]):
                    if seen_children.get(child):
                        modbase_relation[1][idx:idx + 1] = \
                            [[child] + seen_children[child]]

                # record currently encountered relation
                seen_children[parent] = modbase_relation[1]

                # replace the current list with its nested version
                modbase_hierarchy[relation_idx] = modbase_relation

            # add the root to its correct pos. in the hierarchy

            # discard previous nested lists, since the
            # last element now contains the valid nesting
            modbase_hierarchy = modbase_hierarchy[-1]

            # key by the input base of the hierarchical construction,
            # i.e. the unmodfied parent base, taking
            # the position of the empty string from the query
            verified_full_hierarchy_dict[hier_query_base] += \
                modbase_hierarchy[1:]

    # fix the dictionary values, s.t. all doubly-nested lists
    # with only a single item are made into singly-nested lists
    for key, val in verified_full_hierarchy_dict.iteritems():
        fixedVal = deepcopy(val)

        for idx, valL in enumerate(val):
            if is_list(valL) and len(valL) == 1:
                fixedVal[idx] = valL[0]

        verified_full_hierarchy_dict[key] = fixedVal

    verified_full_hierarchy_dict = {key: valL[0] if
                                    (valL[0] and
                                     is_list(valL[0])
                                     and len(valL) == 1)
                                    else valL for key, valL in
                                    verified_full_hierarchy_dict.
                                    iteritems()}

    return verified_full_hierarchy_dict


def get_custom_nomenclature(cursor):
    query = cursor.execute("SELECT * FROM expanded_alphabet")

    col_names = [head[0] for head in query.description]

    # list of entires; each a dict by column name
    res_col_l = [dict(zip(col_names, res))
                 for res in query.fetchall()]

    id_col_name = next(col for col in col_names if 'id' in col.lower())

    # add the ChEBI name to the dict
    name_ID_map = dict(cursor.execute("""SELECT nameid,
                                      chebiname FROM names""").fetchall())

    # return a nested dict, keyed by ChEBI ID, in which each value is a
    # dict with the column names of the nomenclature/expanded alph. table
    return {res_col.pop(id_col_name):
            reduce(lambda x, y: dict(x, **y),
                   (res_col, {'chebiname':
                              name_ID_map[res_col[id_col_name]]}))
            for res_col in res_col_l}


def create_homepage(env, homepage_links, v_base_origins):
    """Loads data needed to create the homepage and creates it."""

    conn = sqlite3.connect(DATABASE_FILE_COPY)
    cursor = conn.cursor()

    verifiedBases = {}
    unverifiedBases = {}

    for base in BASES:
        verifiedBases[base] = homepage_links[base]
        unvername = 'Unverified' + base
        unverifiedBases[base] = homepage_links[unvername]

    verifiedBases['Thymine'] = (verifiedBases['Thymine'] +
                                verifiedBases['Uracil'])
    del(verifiedBases['Uracil'])

    verified_hierarchy_dict = \
        cons_nested_verified_dict_modbase_hierarchy(conn, cursor)

    home_template = env.get_template('homepage.html')

    writefile = os.path.join(HTML_FILES_DIR, 'index.html')

    f = codecs.open(writefile, 'w+', encoding=ENCODING)

    custom_nomenclature = get_custom_nomenclature(cursor)
    for id in custom_nomenclature:
        name = custom_nomenclature[id]['Name']
        custom_nomenclature[id]['Name'] = formatCuratedName(name)

    # record the last modified date (UTC) without the time
    # the resulting datetime object will print in ISO 8601 format
    last_mod_time = os.path.getmtime(DATABASE_FILE_FULLPATH)
    print(datetime.datetime.utcfromtimestamp(last_mod_time))
    last_mod_dt = datetime.datetime.utcfromtimestamp(last_mod_time).date()

    render = home_template.render(bases=VERIFIED_BASES,
                                  modifications=verifiedBases,
                                  verifiedHierarchy=verified_hierarchy_dict,
                                  unverifiedbases=BASES,
                                  unverifiedmodifications=unverifiedBases,
                                  customNomenclature=custom_nomenclature,
                                  vBaseOrigins=v_base_origins,
                                  shadeOrigins=SHADE_ORIGINS,
                                  time=last_mod_dt,
                                  otherRatio=OTHER_RATIO,
                                  otherBase=OTHER_SHARED_BASE,
                                  DnamodVer=DNAMOD_VERSION,
                                  ChebiVer=CHEBI_VERSION)

    f.write(render)
    f.close()


def formatCuratedName(name):
    m = re.search('N\(\d\)', name)
    if m:
        num = re.search('\d', m.group())
        newname = name.replace(m.group(), '<i>N</i><sup>'
                               + num.group() + '</sup>')
        return newname
    else:
        return name


# create the Jinja2 environment object, loading from files
# and disallowing the use of undefined variables
env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
                         undefined=jinja2.StrictUndefined,
                         extensions=JINJA2_EXTENSIONS)

# add custom filters
env.filters['is_list'] = is_list

print("Generating Static Site....")

links, v_base_origins = create_html_pages(env)

create_homepage(env, links, v_base_origins)

print("Static Site Generated")
