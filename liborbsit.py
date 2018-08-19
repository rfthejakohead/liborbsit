#!/usr/bin/python3
# This is probably illegal... ¯\_(ツ)_/¯ oh well
# Library for messing with orbs.it. Use it at your own risk
import http.client
import urllib
import json
import re
import random
import time
import math
from websocket import create_connection

class orbsItOrb:
    def __init__(self, data):
        self.id = data["id"]
        self.owner = data["ownerId"]
        self.changedOwnerTime = data["changedOwnerTime"]
        self.baseAng = data["orbitBaseAng"]
        self.distX = data["orbitDist"]["distX"]
        self.distYCycleAng = data["orbitDist"]["baseDistYCycleAng"]
        self.distYMin = data["orbitDist"]["distYMin"]
        self.distYMax = data["orbitDist"]["distYMax"]
        self.distYRange = data["orbitDist"]["distYRange"]
        self.distYChangeSpeed = data["orbitDist"]["distYChangeSpeed"]
        self.x = None
        self.y = None

    def update(self, gameTime):
        ang = self.baseAng - gameTime / 15
        distyfrac = abs(math.cos(self.distYCycleAng + self.distYChangeSpeed * gameTime))
        self.distY = self.distYMin + self.distYRange * distyfrac
        self.x = self.distX * math.cos(ang)
        self.y = self.distY * math.sin(ang)

    def setOwner(self, pid):
        self.owner = pid

class orbsItPlayer:
    # Orb colours depending on user ID (max 8 players)
    colours = [(255, 0, 0  ), (0, 255, 0  ), (0  , 0  , 255), (255, 255, 0),
               (255, 0, 255), (0, 255, 255), (255, 127, 127), (255, 127, 0)]

    def __init__(self, data):
        self.id = data["id"]
        self.score = data["score"]
        self.bot = data["isBot"]
        self.name = data["name"]
        self.lastFiredTime = data["lastFiredTime"]
        self.lastFirecOrbId = data["lastFiredFromOrbId"]

        if self.bot:
            self.nid = data["nid"]
            self.thinkCyclesWithoutFiring = data["thinkCyclesWithoutFiring"]
        else:
            self.nid = None
            self.thinkCyclesWithoutFiring = None

        self.orbs = []

    def addOrb(self, oid):
        self.orbs.append(oid)

    def remOrb(self, oid):
        self.orbs.remove(oid)

class orbsItGame:
    # Game socket commands
    commands = {"joinGame": 6,
                "gameStatus": 7,
                "initialGameVars": 8,
                "orbHit": 11,
                "eliminated": 14}

    def __init__(self, joinData, user, guid, log = True):
        self.ws = create_connection("ws://" + joinData[0])
        self.joinData = joinData
        self.connected = False
        self.inGame = False
        self.alive = False
        self.gameVars = None
        self.user = user
        self.guid = guid
        self.lastErr = ""
        self.printLog = log
        self.orbs = {}
        self.players = {}

    def log(self, msg, lvl = 1):
        if self.printLog:
            prefix = ["", "INFO: ", "WARN: ", "ERR : "][lvl]
            print(prefix + msg)

    def netUpdate(self):
        data = self.ws.recv().split("\t")
        if data[0] == '':
            return

        data[0] = int(data[0])
        if data[0] == self.commands["gameStatus"]:
            if int(data[1]) < 0:
                self.log("Game has already ended")
                self.inGame = False
                self.disconnect()
        elif data[0] == self.commands["initialGameVars"]:
            self.log("Received initial game variables. Game has started")
            self.alive = True
            self.inGame = True
            self.gameVars = json.loads(data[1])

            if len(data) > 10:
                self.gameStartTime = int(time.time() * 1000) - int(data[2]) - 20
                self.gameTime = float(int(data[2]) / 1000)
            else:
                self.gameStartTime = int(time.time() * 1000) - 20
                self.gameTime = self.gameStartTime / 1000

            for p in self.gameVars["players"]:
                newPlayer = orbsItPlayer(p)
                self.players[newPlayer.id] = newPlayer

            for o in self.gameVars["orbs"]:
                newOrb = orbsItOrb(o)
                self.orbs[newOrb.id] = newOrb
                if newOrb.owner >= 0:
                    self.players[newOrb.owner].addOrb(newOrb.id)
        elif data[0] == self.commands["orbHit"]:
            # TODO: scheduled takes
            orbId = int(data[1])
            oldOwner = self.orbs[orbId].owner
            newOwner = int(data[2])
            if oldOwner >= 0:
                self.players[oldOwner].remOrb(orbId)
            self.orbs[orbId].owner= newOwner
            self.players[newOwner].addOrb(orbId)
            self.log("Orb " + data[1] + " taken by " + data[2])
        elif data[0] == self.commands["eliminated"]:
            if data[1] == "0":
                self.log("You have been eliminated")
                self.alive = False
            else:
                self.log("The game has ended")
                self.inGame = False
                self.disconnect()
        else:
            self.log("Unknown game message:", 3)
            print(data)

    def update(self):
        if not self.connected or not self.inGame:
            return

        self.gameTime = (int(time.time() * 1000) - self.gameStartTime) / 1000
        for i, o in self.orbs.items():
            o.update(self.gameTime)

    def join(self):
        if self.inGame == True:
            lastErr = "Already ingame"
            return False

        self.ws.send(str(self.commands["joinGame"]) + "\t" + self.user + "\t" + str(self.guid) + "\t" + self.joinData[2] + "\t" + self.joinData[3])
        self.connected = True
        return True

    def disconnect(self):
        if not self.connected:
            lastErr = "Not connected"
            return False

        self.ws.close()
        self.connected = False
        return True

class orbsIt:
    libVersion = "0.1a"

    # Action API actions
    actions = {"reqJoinGame": 4,
               "login": 15,
               "userStats": 17,
               "weeklyStats": 18,
               "gameResults": 19,
               "changePassword": 20,
               "alltimeStats": 35}
    # Action API responses
    responses = {"networkErrorVal": 0,
                 "reqJoinGame": 5,
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

    def action(self, action, args = {}, addVersion = False, skipResponseCheck = False, expectedResponse = None):
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
        if expectedResponse != None and int(responseBody[0]) != expectedResponse:
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
        results = self.action(self.actions["gameResults"], {"id": gameId})[1:-3]
        for i in range(len(results)):
            results[i] = json.loads(results[i])
        return results

    def parseGameCommand(self, response):
        response = response.split("\t", 1)
        response[0] = int(response[0])


    def requestJoinGame(self, log = True, gameCode = None, iosMode = False):
        actionDict = {"name": self.name, "sb": 0, "sh": 0, "u": self.guid}
        if gameCode != None:
            actionDict["pgc"] = gameCode

        response = self.action(self.actions["reqJoinGame"], actionDict, True, False, self.responses["reqJoinGame"])
        if response == None:
            self.lastErr = "Failed to request join game"
            return None

        wsAddr = response[0]
        pol = json.loads(response[1])["pols"][0 if iosMode else 1]
        # Unsure what these two represent
        varN = response[2]
        varS = response[3]

        return orbsItGame((wsAddr, pol, varN, varS), self.name, self.guid)

if __name__ == "__main__":
    import pygame
    import _thread as thread

    orbs = orbsIt()
    # Example login, nothing on it
    if not orbs.login("4f10d28bfef7f9381ff0b04f89e1d4bbf64c2aab", "Hz5GdB"):
        print(orbs.lastErr)
        exit()

    pygame.init()
    pygame.mixer.quit()
    area = (800, 600)
    display = pygame.display.set_mode(area)
    pygame.display.set_caption("orbs.it client guid " + str(orbs.guid) + " (liborbsit " + orbsIt.libVersion + ")")
    ticker = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)
    helpText = font.render("[J]oin game; [K]ill connection; [Q]uit", True, (255, 255, 255))

    game = None
    running = True
    drag = False
    dragPos = None
    camZoom = 5
    cam = [-area[0] * camZoom / 2, -area[1] * camZoom / 2]

    def netUpdateLoop(*args):
        while True:
            if not running:
                break
            elif game == None or not game.connected:
                sleep(1)
            else:
                try:
                    game.netUpdate()
                except Exception as e:
                    game.log(str(e), 3)
        game.log("Net update thread terminating")

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 3:
                    drag = True
                    dragPos = event.pos
                elif event.button == 4:
                    if camZoom > 1:
                        anchor = (event.pos[0] * camZoom + cam[0], event.pos[1] * camZoom + cam[1])
                        camZoom -= 1
                        cam[0] = anchor[0] - event.pos[0] * camZoom
                        cam[1] = anchor[1] - event.pos[1] * camZoom
                elif event.button == 5:
                    anchor = (event.pos[0] * camZoom + cam[0], event.pos[1] * camZoom + cam[1])
                    camZoom += 1
                    cam[0] = anchor[0] - event.pos[0] * camZoom
                    cam[1] = anchor[1] - event.pos[1] * camZoom
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 3:
                    drag = False
            elif event.type == pygame.MOUSEMOTION:
                if drag:
                    offset = (dragPos[0] - event.pos[0], dragPos[1] - event.pos[1])
                    dragPos = event.pos
                    cam[0] += offset[0] * camZoom
                    cam[1] += offset[1] * camZoom
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    if game != None:
                        game.disconnect()
                    running = False
                elif event.key == pygame.K_j:
                    if game == None:
                        game = orbs.requestJoinGame()
                        game.join()
                        thread.start_new_thread(netUpdateLoop, ())
                elif event.key == pygame.K_k:
                    if game != None:
                        game.disconnect()
                        game = None

        if game != None:
            game.update()

        display.fill((0,0,0))

        if game != None:
            for i,o in game.orbs.items():
                orbColour = (127, 127, 127)
                if o.owner >= 0:
                    orbColour = orbsItPlayer.colours[o.owner]
                pygame.draw.circle(display, orbColour, (int((o.x - cam[0]) / camZoom), int((o.y - cam[1]) / camZoom)), int(25 / camZoom))
        pygame.draw.circle(display, (255, 255, 0), (int(-cam[0] / camZoom), int(-cam[1] / camZoom)), int(80 / camZoom))
        display.blit(helpText, (0, 0))

        pygame.display.flip()
        ticker.tick(60)

    pygame.quit()
