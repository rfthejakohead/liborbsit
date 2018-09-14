#!/bin/env python3
"""Example Orbs.it client using the library"""

from liborbsit import *
from _thread import start_new_thread
from traceback import print_exc
from getpass import getpass
from time import sleep
import pygame

# Version warning
EXPECTED_LIBORBSIT_VERSION = (0, 4)
if LIBORBSIT_VERSION_INFO[:2] != EXPECTED_LIBORBSIT_VERSION:
    print("liborbsit version mismatch:")
    print("Expected v{:d}.{:d}.x, got {:s}".format(*EXPECTED_LIBORBSIT_VERSION,
                                                   LIBORBSIT_VERSION))

# Ask for login
orbs = orbsIt()
if not orbs.login(input("Enter username: "), getpass("Enter password: ")):
    print(orbs.lastErr)
    exit()

# Declare variables
area = (800, 600)
dragPos = game = playerText = None
drag = False
running = True
selOrb = snapTo = -1
camZoom = 5
cam = [-area[0] * camZoom / 2, -area[1] * camZoom / 2]

# Initialize pygame
pygame.init()
pygame.mixer.quit()
display = pygame.display.set_mode(area, pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.RESIZABLE)
pygame.display.set_caption("orbs.it client guid " + str(orbs.guid) + " (liborbsit " + LIBORBSIT_VERSION + ")")
ticker = pygame.time.Clock()
font = pygame.font.SysFont(None, 24)
helpText = font.render("[J]oin game; [K]ill connection; [Q]uit", True, (255, 255, 255))
timeText = font.render("Game not started", True, (255, 255, 255))
latencyText = font.render("You have received a latency warning!", True, (255, 32, 32))

# Network update loop
def netUpdateLoop(*args):
    while running:
        if game == None or not game.connected:
            sleep(1)
        else:
            try:
                game.netUpdate()
            except WebSocketConnectionClosedException as e:
                continue
            except Exception as e:
                game.log("An exception occurred in the network thread:", 3)
                print_exc()
    game.log("Net update thread terminating")

# Main game loop
while running:
    # Parse events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.VIDEORESIZE:
            area = event.dict['size']
            display = pygame.display.set_mode(area, pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.RESIZABLE)
            pygame.display.flip()
            print("Resized to " + str(area))
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if game != None:
                    clickPos = (event.pos[0] * camZoom + cam[0], event.pos[1] * camZoom + cam[1])
                    skipShot = False
                    for i, o in game.orbs.items():
                        if o.owner != game.playerId:
                            continue
                        dx = abs(clickPos[0] - o.x)
                        dy = abs(clickPos[1] - o.y)
                        d = sqrt(dx * dx + dy * dy)
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
                    start_new_thread(netUpdateLoop, ())
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
        if playerText == None and len(game.players) != 0:
            playerText = dict()
            for i, p in game.players.items():
                name = p.name
                if p.bot:
                    name = "<|o_o|> " + name
                playerText[i] = font.render(name, True, orbsItPlayer.colours[i])
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
            if o.owner >= 0:
                ptext = playerText[o.owner]
                display.blit(ptext, (int((o.x - cam[0]) / camZoom) - ptext.get_width() // 2, int((o.y - cam[1]) / camZoom) - int(50 / camZoom) - 24))
        for b in game.bullets:
            bulletColour = orbsItPlayer.colours[b.owner]
            blife = b.percent()
            bulletColour = (int(bulletColour[0] * blife),
                            int(bulletColour[1] * blife),
                            int(bulletColour[2] * blife))
            pygame.draw.circle(display, bulletColour, (int((b.x - cam[0]) / camZoom), int((b.y - cam[1]) / camZoom)), int(7 / camZoom))
    pygame.draw.circle(display, (255, 255, 0), (int(-cam[0] / camZoom), int(-cam[1] / camZoom)), int(80 / camZoom))
    display.blit(helpText, (0, 0))
    display.blit(timeText, (0, 26))
    if game != None:
        display.blit(font.render("[Z] Shields: {:d}; [X] Smartbombs: {:d}".format(game.myShields, game.mySmartbombs), True, (255, 255, 255)), (0, 52))
        if game.latencyWarning():
            display.blit(latencyText, (0, 78))

    pygame.display.flip()
    ticker.tick(60)

pygame.quit()

