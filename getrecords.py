#!/usr/bin/python

"""
Crawl data from USCIS website
https://egov.uscis.gov/casestatus/mycasestatus.do
"""

import os
import time
import sqlite3
import random
import urllib2
from bs4 import BeautifulSoup, Comment
from mechanize import Browser
from dateutil.parser import parse

ADDRESS = 'https://egov.uscis.gov/casestatus/mycasestatus.do'

def loaduseragents(uafile = 'user_agents.txt'):
    '''Load multiple user agents from a text file.'''
    useragents = []
    with open(uafile, 'rb') as uaf:
        for ua in uaf.readlines():
            if ua:
                useragents.append(ua.strip()[1:-1-1])
    random.shuffle(useragents)
    return useragents


class Crawler:
    def __init__(self, dbname, address = ADDRESS):
        self.con = sqlite3.connect(dbname)
        self.url = ADDRESS
        self.useragents = loaduseragents()
        self.browser = Browser()

    def __del__(self):
        self.con.close()

    def dbcommit(self):
        self.con.commit()

    def getcontent(self, id):
        '''Get contents from html page for given case id.'''
        # randomize headers
        useragent = random.choice(self.useragents)
        header = {"Connection": "close", "User-Agent": useragent}

        # estabish connection
        request = urllib2.Request(self.url, None, header)
        self.browser.open(request)
        self.browser.select_form(nr = 0)
        self.browser['appReceiptNum'] = id

        # get response for a case
        response = self.browser.submit()
        content = response.read()

        return content

    def getstatus(self, status):
        text = status.string.lower()

        if 'received' in text:
            return 0
        elif 'approved' in text:
            return 1
        elif 'additional' in text:
            # further actions requested
            return 3
        elif 'mailed' in text or 'delivered' in text:
            return 2
        elif 'rejected' in text:
            return 4
        else:
            # unrecognized case status
            return 5

    def gettext(self, s):
        text = " ".join(s.find_all(
                        text = lambda t: not isinstance(t, Comment))).lower()
        # string to list
        textlist = text.replace(',', '').split(" ")

        # get date
        try:
            date = parse(" ".join(textlist[1:4])).date()
        except ValueError:
            # no date
            date = None

        # get form type
        try:
            indx = textlist.index('form')
            form = textlist[indx + 1].upper()
        except:
            form = None

        return date, form

    def getinfo(self, id):
        '''Get info for a case with a given id.'''
        content = self.getcontent(id)

        # extract info from html page
        soup = BeautifulSoup(content)
        try:
            status = self.getstatus(soup.find_all('h1')[0])
            date, form = self.gettext(soup.find_all('p')[0])
        # case does not exist
        except IndexError:
            print "All cases are screened..."
            form, status, date = None, None, None

        return id, form, status, date

    def istracked(self, id):
        '''Check if the case already in database.'''
        idx = self.con.execute(
                'SELECT caseid FROM caselist \
                WHERE caseid = "{0}"'.format(id)).fetchone()
        if idx == None:
            return False
        return True

    def isuptodate(self, id, status):
        '''Check if the case is up to date.'''
        currentstatus = self.con.execute(
                        'SELECT status FROM caselist \
                        WHERE caseid = "{0}"'.format(id)).fetchone()
        if currentstatus[0] != status:
            return False
        return True

    def iscomplete(self, form, status, date):
        '''Check if a new case has complete information.'''
        if form == None or status != 0 or date == None:
            return False
        return True

    def isfinished(self, id):
        '''Check if a case is finished, i.e. mailed, rejected, unrecognized.'''
        s = self.con.execute(
                    'SELECT status FROM caselist \
                    WHERE caseid = "{0}"'.format(id)).fetchone()
        if s == 2 or s == 4 or s == 5:
            return True
        return False

    def updatedb(self, id, status, date):
        '''Update an existing case with new status and date.'''
        s = ["received", "approved", "mailed",
             "requested", "rejected", "unrecognized"]
        self.con.execute('UPDATE caselist SET status = {0}, {1} = "{2}" \
                    WHERE caseid = "{3}"'.format(status, s[status], date, id))

    def addtodb(self, id, form, status, date):
        '''Add a new case to database.'''
        s = [None, None, None, None, None, None]
        # update with date
        s[status] = date
        self.con.execute(
         'INSERT INTO caselist(caseid, form, status, received, approved, \
            mailed, requested, rejected, unrecognized) VALUES ("{0}", "{1}", \
            {2}, "{3}", "{4}", "{5}", "{6}", "{7}", "{8}")'.format(id, form, \
            status, s[0], s[1], s[2], s[3], s[4], s[5]))

    def crawl(self, startid, thres = None):
        '''Get info for cases after a given receip number.'''
        # e.g. startid = 'WAC1590447459'
        charid = startid[:3]
        numid = int(startid[3:])
        while True:
            # if only interested in a fixed amount of cases
            if thres != None:
                if numid - int(startid[3:]) > thres:
                    self.dbcommit()
                    break

            # commit every 10 records
            if numid % 10 == 0:
                self.dbcommit()

            if self.isfinished(charid + str(numid)):
                continue

            # sleep between 1 - 5 seconds
            time.sleep(10 + random.randint(1, 5))

            try:
                id, form, status, date = self.getinfo(charid + str(numid))
                numid += 1
            except urllib2.URLError:
                time.sleep(10)
                continue

            # if case in db, check to see if it needs Update
            # otherwise, check if need to add to db
            if status != None:
                if self.istracked(id):
                    if not self.isuptodate(id, status):
                        self.updatedb(id, status, date)
                        print "Update CASE", id
                elif self.iscomplete(form, status, date):
                    self.addtodb(id, form, status, date)
                    print "Add CASE", id
                # if new case is new but incomplete
                else:
                    continue
            # check if no more cases available
            else:
                self.dbcommit()
                break


    def createtable(self):
        '''Create the table for database.'''
        self.con.execute(
             "CREATE TABLE caselist(caseid TEXT, form TEXT, \
                                    status INTEGER, received DATE, \
                                    approved DATE, mailed DATE, \
                                    requested DATE, rejected DATE, \
                                    unrecognized DATE)")
        self.dbcommit()


if __name__ == "__main__":
    dbname = 'records.db'
    crawler = Crawler(dbname)
    if not os.path.isfile(dbname):
        crawler.createtable()
    crawler.crawl('WAC1590446319')
