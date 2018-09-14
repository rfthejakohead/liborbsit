#!/bin/env python3
"""Library for messing with orbs.it. Use it at your own risk"""

from http.client import HTTPConnection
from json import loads as json_loads
from random import randint
from time import time
from math import cos, sin, sqrt, floor
from websocket import create_connection, WebSocketConnectionClosedException

# Library version info: (major, minor, micro, release level)
LIBORBSIT_VERSION_INFO = (0, 4, 0, 'beta')
# Library printable version. Derived from LIBORBSIT_VERSION_INFO
LIBORBSIT_VERSION = "v{:d}.{:d}.{:d} {:s}".format(*LIBORBSIT_VERSION_INFO)

class orbsItOrb:
    """An orb from the game. Has positional properties, owner, etc..."""
    def __init__(self, game: 'orbsItGame', data: dict) -> None:
        """Create a new orb given the server's orb data and a game instance"""
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

    def posAtTime(self, time: float) -> tuple:
        """Get position of orb at a given time"""
        ang = self.baseAng - time / 15
        distyfrac = abs(cos(self.distYCycleAng + self.distYChangeSpeed * time))
        distY = self.distYMin + self.distYRange * distyfrac
        return (self.distX * cos(ang), distY * sin(ang))

    def velAtTime(self, time: float) -> tuple:
        """Get velocity of orb at a given time"""
        # This is a really dirty way to do it but its how the game does it.
        # Should have used calculus and derived a formula instead
        posA = self.posAtTime(time - 0.5)
        posB = self.posAtTime(time + 0.5)
        return (posB[0] - posA[0], posB[1] - posA[1])

    def update(self) -> None:
        """Update the orb's position and cooldowns"""
        ang = self.baseAng - self.game.gameTime / 15
        distyfrac = abs(cos(self.distYCycleAng + self.distYChangeSpeed * self.game.gameTime))
        self.distY = self.distYMin + self.distYRange * distyfrac
        self.x = self.distX * cos(ang)
        self.y = self.distY * sin(ang)
        if self.scheduledTakeTime > 0 and self.scheduledTakeTime <= self.game.gameTime:
            self.scheduledTakeTime = 0
            self.setOwner(self.scheduledTakeBy)
            self.game.log("Orb " + str(self.id) + " taken by " + str(self.owner) + " as per schedule")
        if self.scheduledSmartbombTime > 0 and self.scheduledSmartbombTime <= self.game.gameTime:
            angle = 0.0
            while angle <= 315.0:
                self.shoot(self.scheduledSmartbombTime, (cos(0.0174533 * angle), sin(0.0174533 * angle)))
                angle += 22.5
            self.scheduledSmartbombTime = 0
            self.game.log("Orb " + str(self.id) + " deployed smartbomb as per schedule")

    def setOwner(self, pid: int) -> None:
        """Set the orb's owner"""
        if self.owner >= 0:
            self.game.players[self.owner].orbs.remove(self.id)
        self.owner = pid
        self.game.players[self.owner].orbs.append(self.id)
        # If the time between now and the last shot is less than a second, set
        # the last shot time so that the difference is at least a second.
        # Basically, add a delay if you are able to almost instantly shoot
        if self.game.gameTime - self.lastShot < 1:
            self.lastShot = self.game.gameTime - 1

    def shoot(self, time: float, normal: tuple) -> None:
        """Shoot a bullet from this orb given its normal, at a given time"""
        # Only verify countdown when player owns the orb (at playerShoot)
        self.lastShot = time
        # 250 is the impulse multiplier constant
        impulse = (normal[0] * 250, normal[1] * 250)
        self.game.bullets.append(orbsItBullet(self, time, impulse))
        # If the difference between the shoot time and user's game time is late,
        # tweak it (more than 1/5 seconds)
        if self.game.gameTime - time < -0.2:
            self.game.log("Latency detected by orb shoot")
            self.game.timeTweak -= 30
            self.game.latencyWarnings += 1

    def playerShoot(self, clickPos: tuple) -> None:
        """As a player, shoot a bullet from this orb"""
        # Just in case there is a race condition
        # Its pointless to skip last shot time check as the server has
        # anti-cheat which disconnects you when you shoot too often
        if self.owner == self.game.playerId and self.game.gameTime - self.lastShot >= 2:
            sx = clickPos[0] - self.x
            sy = clickPos[1] - self.y
            sd = sqrt(sx * sx + sy * sy)
            sx /= sd
            sy /= sd
            self.shoot(self.game.gameTime, (sx, sy))
            # Call your own shots. Game time is always 3 dp due to div. by 1000
            self.game.netSend("{:d}\t{:d}\t{:.3f}\t{:.4f}\t{:.4f}".format(self.game.commands["shoot"], self.id, self.game.gameTime, sx, sy))

    def deployShield(self, time: float) -> None:
        """Deploy shield on this orb, at a given time"""
        # Original game code only counts down 4.5 seconds, but doesn't pay
        # attention to scheduled time deploy delay, so this will count time
        # from deploy time instead of counting down 4.5 seconds fixing possible
        # exploits
        self.scheduledShieldTime = time

    def shieldUp(self) -> None:
        """Get if there is a shield currently on this orb"""
        return self.game.gameTime >= self.scheduledShieldTime and self.game.gameTime < self.scheduledShieldTime + 4.5

    def playerShield(self) -> None:
        """As a player, deploy a shield on this orb"""
        # Just in case there is a race condition
        if self.owner == self.game.playerId and not self.shieldUp() and self.game.myShields > 0 and self.game.shieldCooldownTime < self.game.gameTime:
            self.game.netSend("{:d}\t{:d}\t{:.3f}".format(self.game.commands["deployShield"], self.id, self.game.gameTime))
            # 7 seconds is the cooldown for both shields and smartbombs
            self.game.shieldCooldownTime = self.game.gameTime + 7

    def deploySmartbomb(self, time: float) -> None:
        """Deploy a smartbomb (multi-shot) from this orb, at a given time"""
        self.scheduledSmartbombTime = time

    def playerSmartbomb(self) -> None:
        """As a player, deploy a smartbomb (multi-shot) from this orb"""
        # Just in case there is a race condition
        if self.owner == self.game.playerId and self.scheduledSmartbombTime == 0 and self.game.mySmartbombs > 0 and self.game.smartbombCooldownTime < self.game.gameTime:
            self.game.netSend("{:d}\t{:d}\t{:.3f}".format(self.game.commands["deploySmartbomb"], self.id, self.game.gameTime))
            # 7 seconds is the cooldown for both shields and smartbombs
            self.game.smartbombCooldownTime = self.game.gameTime + 7

class orbsItPlayer:
    """A player from the game. Has id, score, name, states, etc..."""
    # Orb colours depending on user ID (max 8 players)
    colours = [(255, 0, 0  ), (0, 255, 0  ), (0  , 0  , 255), (255, 255, 0),
               (255, 0, 255), (0, 255, 255), (255, 127, 127), (255, 127, 0)]

    def __init__(self, data: list) -> None:
        """Create a new player given the server's player data"""
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
    """A bullet from the game. Has position, owner, source, etc..."""
    def __init__(self, source: orbsItOrb, time: float, impulse: tuple) -> None:
        """Create a bullet given the source orb, timestamp and impulse"""
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

    def alive(self) -> bool:
        """Check if the bullet is currently alive (hasn't expired)"""
        return self.game.gameTime < self.birth + 3

    def percent(self) -> float:
        """Convert the bullet's current life to a range of 1.0 to 0.0"""
        lifespan = (self.game.gameTime - self.birth) / 3
        if lifespan < 0.0:
            lifespan = 0.0
        elif lifespan > 1.0:
            lifespan = 1.0
        return 1.0 - lifespan

    def update(self) -> None:
        """Update the bullet's position and check for collisions"""
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
                d = sqrt(dx * dx + dy * dy)
                hd = 47 if o.shieldUp() else 32
                if d < hd:
                    self.game.bullets.remove(self)
                    if self.owner == self.game.playerId and o.owner != self.game.playerId and o.scheduledTakeTime == 0:
                        # Call your own hits. There is no room for exploit here,
                        # as the server seems to have some sort of anti-cheat
                        self.game.netSend("{:d}\t{:d}\t{:d}\t{:.3f}\t{:.3f}".format(self.game.commands["orbHit"], o.id, self.source, self.birth, self.game.gameTime))

class orbsItGame:
    """An Orbs.it game client. Contains all game data and states"""
    # Game socket commands
    commands = {"joinGame": 6,
                "gameStatus": 7,
                "initialGameVars": 8,
                "initialPlayerVars": 9,
                "shoot": 10,
                "orbHit": 11,
                "latencyDelay": 12,
                "latencyWarning": 13,
                "eliminated": 14,
                "deployShield": 21,
                "deploySmartbomb": 23,
                "bonusPowerup": 24}
    latencyCommands = [12, 13] # latencyDelay and latencyWarning

    def __init__(self, joinData: tuple, user: str, guid: int, gameCode: str = None, log: bool = True) -> None:
        """Create a new game given the server's requested game data"""
        # Connection variables
        self.joinData = joinData
        self.ws = create_connection("ws://" + joinData[0])
        self.connected = False
        self.latencyWarningEndTime = 0
        self.latencyWarnings = 0

        # Settings variables
        self.lastErr = ""
        self.printLog = log

        # Global game variables
        self.gameVars = None
        self.inGame = False
        self.orbs = {}
        self.players = {}
        self.bullets = []
        # Start times are in milliseconds, while game time is in seconds
        self.gameStartTimeUntweaked = None
        self.gameStartTime = None
        self.gameTime = None
        self.gameCode = gameCode
        self.timeTweak = 0

        # Player game variables
        self.user = user
        self.guid = guid
        self.alive = False
        self.playerId = -1
        self.myShieldsCarried = 0
        self.myShields = 0
        self.mySmartbombsCarried = 0
        self.mySmartbombs = 0
        self.shieldCooldownTime = 0
        self.smartbombCooldownTime = 0

    def log(self, msg: str, lvl: int = 1) -> None:
        """Log a message with a log level. Follows game log preferences"""
        if self.printLog:
            prefix = ["", "INFO: ", "WARN: ", "ERR : "][lvl]
            print(prefix + msg)

    def netSend(self, msg: str) -> None:
        """Broadcast a websocket message. Not used outside library"""
        self.log("Broadcasting message: " + msg)
        self.ws.send(msg)

    def netUpdate(self) -> None:
        """Listen for network events in websocket. Typically threaded by user"""
        message = self.ws.recv()
        data = message.split("\t")
        if data[0] == '':
            return

        self.log("Received broadcast: " + message)
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
            self.gameVars = json_loads(data[1])

            if len(data) > 10:
                self.gameStartTime = int(time() * 1000) - int(data[2]) - 20
                self.gameTime = float(int(data[2]) / 1000)
            else:
                self.gameStartTime = int(time() * 1000) - 20
                self.gameTime = self.gameStartTime / 1000
            self.gameStartTimeUntweaked = self.gameStartTime

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
        elif data[0] in self.latencyCommands:
            self.latencyWarnings += 1
            if data[0] == self.commands["latencyDelay"]:
                self.timeTweak += 30
                self.log("Received a delayed latency warning")
            else:
                self.log("Received a latency warning")
        elif data[0] == self.commands["bonusPowerup"]:
            if int(data[0]) == 1:
                self.log("Received shield powerup. Shield cooldown reset")
                self.myShields += 1
                self.shieldCooldownTime = self.gameTime
            else:
                self.log("Received smartbomb powerup. Smartbomb cooldown reset")
                self.mySmartbombs += 1
                self.shieldCooldownTime = self.gameTime
        else:
            self.log("Unknown game message:", 3)
            print(data)

    def update(self) -> None:
        """Update game objects. Typically called in game loop"""
        if not self.connected or not self.inGame:
            return

        self.gameTime = (int(time() * 1000) - self.gameStartTime) / 1000
        self.createDelay()
        for i, o in self.orbs.items():
            o.update()
        killList = []
        for b in self.bullets:
            b.update()
            if not b.alive():
                killList.append(b)
        for b in killList:
            self.bullets.remove(b)

    def join(self) -> bool:
        """Join the game if not already joined"""
        if self.inGame:
            lastErr = "Already ingame"
            return False

        suffix = ""
        if self.gameCode != None:
            suffix += "\t" + self.gameCode

        self.ws.send(str(self.commands["joinGame"]) + "\t" + self.user + "\t" + str(self.guid) + "\t" + self.joinData[2] + "\t" + self.joinData[3] + suffix)
        self.connected = True
        return True

    def disconnect(self) -> bool:
        """Disconnect from the game if ingame"""
        if not self.connected:
            lastErr = "Not connected"
            return False

        self.ws.close()
        self.connected = False
        return True

    def latencyWarning(self) -> bool:
        """Get wether there is a currently active latency warning"""
        if self.gameTime == None:
            return False
        return self.gameTime < self.latencyWarningEndTime

    def createDelay(self) -> None:
        """Create a time delay. Not used outside library"""
        if self.timeTweak != 0:
            tweakedTime = self.gameStartTime + floor(0.5 + self.timeTweak / 20)
            self.timeTweak *= 19 / 20
            if abs(self.timeTweak) < 20:
                self.timeTweak = 0
            tweakImpact = tweakedTime - self.gameStartTimeUntweaked
            if tweakImpact > -600 and tweakImpact < 30:
                self.gameStartTime = tweakedTime
                # In the original game code, the bullets are delayed, but since
                # they are calculated from their starting time instead of delta
                # it is unneccessary here

class orbsIt:
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

    def __init__(self, ip: str = "85.10.196.164", port: int = 19330, version: str = "1.1") -> None:
        self.ip = ip
        self.port = str(port)
        self.version = version
        self.http = HTTPConnection(ip, port, timeout=10)
        self.lastErr = ""
        self.guid = None
        self.loginName = None
        self.name = None
        self.password = None
        self.countdown = None

    def action(self, action: int, args: dict = None, addVersion: bool = False, skipResponseCheck: bool = False, expectedResponse: int = None) -> list:
        # On error, returns None
        if args == None:
            args = {}

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

    def login(self, username: str = "", password: str = "", bypassConstraints: bool = False) -> bool:
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
                    password += pCharset[randint(0, len(pCharset) - 1)]

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

    def changePassword(self, newPassword: str) -> bool:
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

    def weeklyStats(self) -> list:
        stats = self.action(self.actions["weeklyStats"])
        self.countdown = int(stats[1])
        return json_loads(stats[0])["data"]

    def alltimeStats(self) -> list:
        stats = self.action(self.actions["alltimeStats"], {}, False, True)
        # For some reason the devs decided that [0] = 'x', so remove it. Also
        # it's not JSON, it's tab separated. That's annoying
        stats = stats.split('\t')[1:]
        statsPaired = []
        for i in range(0, len(stats), 2):
            statsPaired.append(tuple(stats[i:i+2]))
        return statsPaired

    def userStats(self, guid: int = None) -> dict:
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
        return json_loads(stats[0])

    def gameResults(self, gameId: int) -> list:
        # The response for this request is padded with extra strange tabbed data
        # which I cannot figure out what it is about, since it's not even used
        # in the game code. It seems to change from id to id. Just ignore it
        results = self.action(self.actions["gameResults"], {"id": gameId})[1:-3]
        for i in range(len(results)):
            results[i] = json_loads(results[i])
        return results

    def requestJoinGame(self, gameCode: str = None, iosMode: bool = False, log: bool = True) -> orbsItGame:
        actionDict = {"name": self.name, "sb": 0, "sh": 0, "u": self.guid}
        if gameCode != None:
            actionDict["pgc"] = gameCode

        response = self.action(self.actions["reqJoinGame"], actionDict, True, False, self.responses["reqJoinGame"])
        if response == None:
            self.lastErr = "Failed to request join game"
            return None

        wsAddr = response[0]
        pol = json_loads(response[1])["pols"][0 if iosMode else 1]
        # Unsure what these two represent
        varN = response[2]
        varS = response[3]

        return orbsItGame((wsAddr, pol, varN, varS), self.name, self.guid, gameCode)
