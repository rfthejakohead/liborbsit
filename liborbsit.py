#!/usr/bin/python3
# This is probably illegal... ¯\_(ツ)_/¯ oh well
# Library for messing with orbs.it. Use it at your own risk
import http.client
import urllib
import json
import re
import random

class orbsIt:
    actions = {"login": 15,
               "userStats": 17,
               "weeklyStats": 18,
               "gameResults": 19,
               "changePassword": 20,
               "alltimeStats": 35}
    responses = {"networkErrorVal": 0,
                 "login": 16}

    def __init__(self, ip = "85.10.196.164", port = 19330, version = "1.1"):
        self.ip = ip
        self.port = str(port)
        self.version = version
        self.http = http.client.HTTPConnection(ip, port, timeout=10)
        self.lastErr = ""
        self.guid = None
        self.loginName = None
        self.name = None
        self.password = None
        self.countdown = None

    def action(self, action, args = {}, addVersion = False, skipResponseCheck = False):
        # On error, returns None
        argsSuffix = ""
        for arg, val in args.items():
            argsSuffix += "&" + str(arg) + "=" + str(val)

        if addVersion:
            argsSuffix += "&v=" + self.version

        self.http.request("GET", "/?action=" + str(action) + argsSuffix)
        response = self.http.getresponse()
        if response.status != 200:
            return None

        if skipResponseCheck:
            return response.read().decode()

        responseBody = response.read().decode().split('\t')
        if int(responseBody[0]) == self.responses['networkErrorVal']:
            return None

        return responseBody[1:]

    def login(self, username = "", password = "", bypassConstraints = False):
        # orbs does some funny stuff to usernames and passwords when creating
        # at some conditions. It only does some sort of partial server sided
        # checking, so it does what it does here (trimming etc) but it creates
        # a new guid every time, so duplicates are created every time you
        # login with auth details that break these constraints
        if not bypassConstraints:
            username = username.strip()
            if len(username) > 30:
                username = username[:30]
            # This is also in the code believe it or not. Kinda useless now,
            # its already taken and the account is probably dead
            if username == "":
                username = "Lazy"

            if password == "":
                pCharset = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                for i in range(6):
                    password += pCharset[random.randint(0, len(pCharset) - 1)]

        res = self.action(self.actions["login"], {"n": username, "p": password}, True)
        if res == None:
            self.lastErr = "Could not login"
            return False
        elif res[0] == "ok":
            self.name = username
            self.password = password
            self.guid = int(res[1])
            return True
        elif res[0] == "badpsw":
            self.lastErr = "Could not login: Bad password"
            return False
        else:
            self.lastErr = "Could not login: Unknown response; " + res[0]
            return False

    def changePassword(self, newPassword):
        if self.guid == None:
            self.lastErr = "Not logged in"
            return

        res = self.action(self.actions["changePassword"], {"u": self.guid, "p1": self.password, "p2": newPassword})
        if res == None:
            self.lastErr = "Could not change password"
            return False
        elif res[0] == "ok":
            self.password = newPassword
            return True
        else:
            self.lastErr = "Could not change password: Unknown response; " + res[0]
            return False

    def weeklyStats(self):
        stats = self.action(self.actions["weeklyStats"])
        self.countdown = int(stats[1])
        return json.loads(stats[0])["data"]

    def alltimeStats(self):
        stats = self.action(self.actions["alltimeStats"], {}, False, True)
        # For some reason the devs decided that [0] = 'x', so remove it. Also
        # it's not JSON, it's tab separated. That's annoying
        stats = stats.split('\t')[1:]
        statsPaired = []
        for i in range(0, len(stats), 2):
            statsPaired.append(tuple(stats[i:i+2]))
        return statsPaired

    def userStats(self, guid = None):
        if guid == None and self.guid == None:
            self.lastErr = "Not logged in"
            return None
        if guid != None and guid < 0:
            # Turns out there are A LOT of bots... and they all have negative
            # GUIDs. I feel like I'm not as good as I thought I was in this game
            self.lastErr = "Cannot get stats of a bot (bots have negative GUIDs)"
            return None

        stats = self.action(self.actions["userStats"], {"u": guid if (guid != None) else self.guid})
        if stats == None:
            return None
        self.countdown = int(stats[1])
        return json.loads(stats[0])

    def gameResults(self, gameId):
        # The response for this request is padded with extra strange tabbed data
        # which I cannot figure out what it is about, since it's not even used
        # in the game code. It seems to change from id to id. Just ignore it
        results = self.action(self.actions["gameResults"], {"id": str(gameId)})[1:-3]
        for i in range(len(results)):
            results[i] = json.loads(results[i])
        return results

    def requestJoinGame(self, gameCode = None):
        pass

if __name__ == "__main__":
    orbs = orbsIt()
    # Example login, nothing on it
    if not orbs.login("4f10d28bfef7f9381ff0b04f89e1d4bbf64c2aab", "Hz5GdB"):
        print(orbs.lastErr)
        exit()

    print("Your global user ID is " + str(orbs.guid))
    print(orbs.userStats())
