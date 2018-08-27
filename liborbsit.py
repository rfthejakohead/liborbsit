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
    def __init__(self, game, data):
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
        self.scheduledTakeTime = 0
        self.scheduledTakeBy = None
        self.game = game
        self.scheduledShieldTime = 0
        self.scheduledSmartbombTime = 0
        self.lastShot = 0

        if self.owner >= 0:
            self.game.players[self.owner].orbs.append(self.id)

    def posAtTime(self, time):
        ang = self.baseAng - time / 15
        distyfrac = abs(math.cos(self.distYCycleAng + self.distYChangeSpeed * time))
        distY = self.distYMin + self.distYRange * distyfrac
        return (self.distX * math.cos(ang), distY * math.sin(ang))

    def velAtTime(self, time):
        # This is a really dirty way to do it but its how the game does it.
        # Should have used calculus and derived a formula instead
        posA = self.posAtTime(time - 0.5)
        posB = self.posAtTime(time + 0.5)
        return (posB[0] - posA[0], posB[1] - posA[1])

    def update(self):
        ang = self.baseAng - self.game.gameTime / 15
        distyfrac = abs(math.cos(self.distYCycleAng + self.distYChangeSpeed * self.game.gameTime))
        self.distY = self.distYMin + self.distYRange * distyfrac
        self.x = self.distX * math.cos(ang)
        self.y = self.distY * math.sin(ang)
        if self.scheduledTakeTime > 0 and self.scheduledTakeTime <= self.game.gameTime:
            self.scheduledTakeTime = 0
            self.setOwner(self.scheduledTakeBy)
            self.game.log("Orb " + str(self.id) + " taken by " + str(self.owner) + " as per schedule")
        if self.scheduledSmartbombTime > 0 and self.scheduledSmartbombTime <= self.game.gameTime:
            angle = 0.0
            while angle <= 315.0:
                self.shoot(self.scheduledSmartbombTime, (math.cos(0.0174533 * angle), math.sin(0.0174533 * angle)))
                angle += 22.5
            self.scheduledSmartbombTime = 0
            self.game.log("Orb " + str(self.id) + " deployed smartbomb as per schedule")

    def setOwner(self, pid):
        if self.owner >= 0:
            self.game.players[self.owner].orbs.remove(self.id)
        self.owner = pid
        self.game.players[self.owner].orbs.append(self.id)

    def shoot(self, time, normal):
        # Only verify countdown when player owns the orb (at playerShoot)
        self.lastShot = time
        # 250 is the impulse multiplier constant
        impulse = (normal[0] * 250, normal[1] * 250)
        self.game.bullets.append(orbsItBullet(self, time, impulse))

    def playerShoot(self, clickPos):
        # Just in case there is a race condition
        # Its pointless to skip last shot time check as the server has
        # anti-cheat which disconnects you when you shoot too often
        if self.owner == self.game.playerId and self.game.gameTime - self.lastShot >= 2:
            sx = clickPos[0] - self.x
            sy = clickPos[1] - self.y
            sd = math.sqrt(sx * sx + sy * sy)
            sx /= sd
            sy /= sd
            self.shoot(self.game.gameTime, (sx, sy))
            # Call your own shots. For some reason gameTime is not rounded to
            # 4 decimal places in the original game code, so emulating JS limits
            # here (float.toString rounds to 16 DP)
            self.game.netSend("{:d}\t{:d}\t{:.16f}\t{:.4f}\t{:.4f}".format(self.game.commands["shoot"], self.id, self.game.gameTime, sx, sy))

    def deployShield(self, time):
        # Original game code only counts down 4.5 seconds, but doesn't pay
        # attention to scheduled time deploy delay, so this will count time
        # from deploy time instead of counting down 4.5 seconds fixing possible
        # exploits
        self.scheduledShieldTime = time

    def shieldUp(self):
        if self.game.gameTime >= self.scheduledShieldTime and self.game.gameTime < self.scheduledShieldTime + 4.5:
            return True
        return False

    def playerShield(self):
        # Just in case there is a race condition
        if self.owner == self.game.playerId and not self.shieldUp() and self.game.myShields > 0:
            self.game.netSend("{:d}\t{:d}\t{:.4f}".format(self.game.commands["deployShield"], self.id, self.game.gameTime))

    def deploySmartbomb(self, time):
        self.scheduledSmartbombTime = time

    def playerSmartbomb(self):
        # Just in case there is a race condition
        if self.owner == self.game.playerId and self.scheduledSmartbombTime == 0 and self.game.mySmartbombs > 0:
            self.game.netSend("{:d}\t{:d}\t{:.4f}".format(self.game.commands["deploySmartbomb"], self.id, self.game.gameTime))

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

class orbsItBullet:
    def __init__(self, source, time, impulse):
        self.game = source.game
        # Start position. Current position will always be calculated from the
        # start position, opposed to how the original game code does it, so that
        # timed network exploits are prevented
        self.vx, self.vy = source.velAtTime(time)
        self.vx += impulse[0]
        self.vy += impulse[1]
        self.sx, self.sy = source.posAtTime(time)
        self.sx += + self.vx / 10
        self.sy += + self.vy / 10
        self.x = self.sx
        self.y = self.sy
        self.owner = source.owner
        self.source = source.id
        self.birth = time # The lifespan of bullets is exactly 3 seconds

    def alive(self):
        if self.game.gameTime < self.birth + 3:
            return True
        return False

    def update(self):
        lifespan = self.game.gameTime - self.birth
        self.x = self.sx + self.vx * lifespan
        self.y = self.sy + self.vy * lifespan

        # Collision check with all orbs
        for i, o in self.game.orbs.items():
            # Skip source orb
            if i != self.source:
                # Normal hit distance is 32
                # Shield hit distance is 47
                dx = abs(self.x - o.x)
                dy = abs(self.y - o.y)
                d = math.sqrt(dx * dx + dy * dy)
                hd = 47 if o.shieldUp() else 32
                if d < hd:
                    self.game.bullets.remove(self)
                    if self.owner == self.game.playerId and o.owner != self.game.playerId and o.scheduledTakeTime == 0:
                        # Call your own hits. There is room for exploit here...
                        # plis dont
                        self.game.netSend("{:d}\t{:d}\t{:d}\t{:.4f}\t{:.4f}".format(self.game.commands["orbHit"], o.id, self.source, self.birth, self.game.gameTime))

class orbsItGame:
    # Game socket commands
    commands = {"joinGame": 6,
                "gameStatus": 7,
                "initialGameVars": 8,
                "initialPlayerVars": 9,
                "shoot": 10,
                "orbHit": 11,
                "eliminated": 14,
                "deployShield": 21,
                "deploySmartbomb": 23,
                "bonusPowerup": 24}

    def __init__(self, joinData, user, guid, gameCode = None, log = True):
        # Connection variables
        self.joinData = joinData
        self.ws = create_connection("ws://" + joinData[0])
        self.connected = False

        # Settings variables
        self.lastErr = ""
        self.printLog = log

        # Global game variables
        self.gameVars = None
        self.inGame = False
        self.orbs = {}
        self.players = {}
        self.bullets = []
        self.gameStartTime = None
        self.gameTime = None
        self.gameCode = gameCode

        # Player game variables
        self.user = user
        self.guid = guid
        self.alive = False
        self.playerId = -1
        self.myShieldsCarried = 0
        self.myShields = 0
        self.mySmartbombsCarried = 0
        self.mySmartbombs = 0

    def log(self, msg, lvl = 1):
        if self.printLog:
            prefix = ["", "INFO: ", "WARN: ", "ERR : "][lvl]
            print(prefix + msg)

    def netSend(self, msg):
        self.log("Broadcasting message: " + msg)
        self.ws.send(msg)

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
                newOrb = orbsItOrb(self, o)
                self.orbs[newOrb.id] = newOrb
        elif data[0] == self.commands["initialPlayerVars"]:
            self.log("Received initial player variables")
            self.playerId = int(data[1])
            self.myShieldsCarried = int(data[2])
            self.myShields = 2 + self.myShieldsCarried
            self.mySmartbombsCarried = int(data[3])
            self.mySmartbombs = 2 + self.mySmartbombsCarried
        elif data[0] == self.commands["shoot"]:
            orbId = int(data[1])
            shootTime = float(data[2])
            normal = (float(data[3]), float(data[4]))
            self.orbs[orbId].shoot(shootTime, normal)
            self.log("Orb " + data[1] + " shot bullet at time " + data[2] + " with direction normal (" + data[3] + ", " + data[4] + ")")
        elif data[0] == self.commands["orbHit"]:
            orbId = int(data[1])
            newOwner = int(data[2])
            takeTime = float(data[3])

            # If the take time is in the future, schedule it
            if takeTime > self.gameTime:
                # If the orb is taken before the current schedule, replace
                if self.orbs[orbId].scheduledTakeTime <= takeTime:
                    self.orbs[orbId].scheduledTakeTime = takeTime
                    self.orbs[orbId].scheduledTakeBy = newOwner
                    self.log("Orb " + data[1] + " scheduled to be taken by " + data[2] + " at time " + data[3])
            else:
                self.orbs[orbId].setOwner(newOwner)
                self.log("Orb " + data[1] + " taken by " + data[2])
        elif data[0] == self.commands["eliminated"]:
            if data[1] == "0":
                self.log("You have been eliminated")
                self.alive = False
            else:
                self.log("The game has ended")
                self.inGame = False
                self.disconnect()
        elif data[0] == self.commands["deployShield"]:
            targetOrb = int(data[1])
            deployTime = float(data[2])
            self.orbs[targetOrb].deployShield(deployTime)
            if self.orbs[targetOrb].owner == self.playerId:
                self.myShields -= 1
                self.log("You have orb " + data[1] + " scheduled to deploy a shield at time " + data[2])
            else:
                self.log("Orb " + data[1] + " scheduled to deploy a shield at time " + data[2])
        elif data[0] == self.commands["deploySmartbomb"]:
            targetOrb = int(data[1])
            deployTime = float(data[2])
            self.orbs[targetOrb].deploySmartbomb(deployTime)
            if self.orbs[targetOrb].owner == self.playerId:
                self.mySmartbombs -= 1
                self.log("You have orb " + data[1] + " scheduled to deploy a smartbomb at time " + data[2])
            else:
                self.log("Orb " + data[1] + " scheduled to deploy a smartbomb at time " + data[2])
        elif data[0] == self.commands["bonusPowerup"]:
            # TODO: myPowerupsAvailableFrom assignments and pr() call
            if int(data[0]) == 1:
                self.log("Received shield powerup")
                self.myShields += 1
            else:
                self.log("Received smartbomb powerup")
                self.mySmartbombs += 1
        else:
            self.log("Unknown game message:", 3)
            print(data)

    def update(self):
        if not self.connected or not self.inGame:
            return

        self.gameTime = (int(time.time() * 1000) - self.gameStartTime) / 1000
        for i, o in self.orbs.items():
            o.update()
        killList = []
        for b in self.bullets:
            b.update()
            if not b.alive():
                killList.append(b)
        for b in killList:
            self.bullets.remove(b)

    def join(self):
        if self.inGame == True:
            lastErr = "Already ingame"
            return False

        suffix = ""
        if self.gameCode != None:
            suffix += "\t" + self.gameCode

        self.ws.send(str(self.commands["joinGame"]) + "\t" + self.user + "\t" + str(self.guid) + "\t" + self.joinData[2] + "\t" + self.joinData[3] + suffix)
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
    libVersion = "0.2a"

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


    def requestJoinGame(self, gameCode = None, iosMode = False, log = True):
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

        return orbsItGame((wsAddr, pol, varN, varS), self.name, self.guid, gameCode)

if __name__ == "__main__":
    import pygame
    import _thread as thread
    import traceback
    import sys

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
    timeText = font.render("Game not started", True, (255, 255, 255))

    game = None
    running = True
    drag = False
    dragPos = None
    camZoom = 5
    cam = [-area[0] * camZoom / 2, -area[1] * camZoom / 2]
    selOrb = -1
    snapTo = -1

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
                    game.log("An exception occurred in the network thread:", 3)
                    traceback.print_exc(file=sys.stdout)
        game.log("Net update thread terminating")

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    if game != None:
                        clickPos = (event.pos[0] * camZoom + cam[0], event.pos[1] * camZoom + cam[1])
                        skipShot = False
                        for i, o in game.orbs.items():
                            dx = abs(clickPos[0] - o.x)
                            dy = abs(clickPos[1] - o.y)
                            d = math.sqrt(dx * dx + dy * dy)
                            if d <= 25 and not drag:
                                selOrb = i
                                snapTo = i
                                skipShot = True
                                break
                        if selOrb >= 0 and not skipShot:
                            game.orbs[selOrb].playerShoot(clickPos)
                elif event.button == 3:
                    drag = True
                    dragPos = event.pos
                    snapTo = -1
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
                        timeText = font.render("Disconnected", True, (255, 255, 255))
                elif event.key == pygame.K_c:
                    if game != None:
                        game.orbs[selOrb].playerShield()
                elif event.key == pygame.K_x:
                    if game != None:
                        game.orbs[selOrb].playerSmartbomb()

        if game != None:
            game.update()
            if game.gameTime != None:
                timeText = font.render("Game time: " + str(game.gameTime), True, (255, 255, 255))
            if snapTo >= 0:
                cam[0] = game.orbs[snapTo].x - area[0] * camZoom / 2
                cam[1] = game.orbs[snapTo].y - area[1] * camZoom / 2

        display.fill((0,0,0))

        if game != None:
            for i,o in game.orbs.items():
                orbColour = (127, 127, 127)
                if o.owner >= 0:
                    orbColour = orbsItPlayer.colours[o.owner]
                # Too lazy for transparency, so I'll just do a quick n' dirty under-draw
                if o.shieldUp():
                    pygame.draw.circle(display, (192, 192, 192), (int((o.x - cam[0]) / camZoom), int((o.y - cam[1]) / camZoom)), int(36.71875 / camZoom))
                pygame.draw.circle(display, orbColour, (int((o.x - cam[0]) / camZoom), int((o.y - cam[1]) / camZoom)), int(25 / camZoom))
            for b in game.bullets:
                bulletColour = orbsItPlayer.colours[b.owner]
                pygame.draw.circle(display, bulletColour, (int((b.x - cam[0]) / camZoom), int((b.y - cam[1]) / camZoom)), int(10 / camZoom))
        pygame.draw.circle(display, (255, 255, 0), (int(-cam[0] / camZoom), int(-cam[1] / camZoom)), int(80 / camZoom))
        display.blit(helpText, (0, 0))
        display.blit(timeText, (0, 26))

        pygame.display.flip()
        ticker.tick(60)

    pygame.quit()
