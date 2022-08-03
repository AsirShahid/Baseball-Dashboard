#!/usr/bin/env python3

import pybaseball as pyb
from pybaseball import team_batting
from pybaseball import team_pitching
from pybaseball import team_fielding
from pybaseball import batting_stats
from pybaseball import pitching_stats
from pybaseball import fielding_stats
import pandas as pd
import os
# Import sleep
from time import sleep

pyb.cache.disable()

# Find year
import datetime
year = datetime.datetime.now().year

# if team_batting directory does not exist, create it
if not os.path.exists(os.path.join(os.getcwd(), 'team_batting')):
    os.makedirs(os.path.join(os.getcwd(), 'team_batting'))
# if team_pitching directory does not exist, create it
if not os.path.exists(os.path.join(os.getcwd(), 'team_pitching')):
    os.makedirs(os.path.join(os.getcwd(), 'team_pitching'))
# if team_fielding directory does not exist, create it
if not os.path.exists(os.path.join(os.getcwd(), 'team_fielding')):
    os.makedirs(os.path.join(os.getcwd(), 'team_fielding'))
# if qualified_batting_stats directory does not exist, create it
if not os.path.exists(os.path.join(os.getcwd(), 'qualified_batting_stats')):
    os.makedirs(os.path.join(os.getcwd(), 'qualified_batting_stats'))
# if qualified_pitching_stats directory does not exist, create it
if not os.path.exists(os.path.join(os.getcwd(), 'qualified_pitching_stats')):
    os.makedirs(os.path.join(os.getcwd(), 'qualified_pitching_stats'))
# if all_batting_stats directory does not exist, create it
if not os.path.exists(os.path.join(os.getcwd(), 'all_batting_stats')):
    os.makedirs(os.path.join(os.getcwd(), 'all_batting_stats'))
# if all_pitching_stats directory does not exist, create it
if not os.path.exists(os.path.join(os.getcwd(), 'all_pitching_stats')):
    os.makedirs(os.path.join(os.getcwd(), 'all_pitching_stats'))

# Get team batting data from 1871 to current year
# for i in range(year,1870, -1):
# # Turn data into csv file in their own directory
#     team_batting(i).to_csv('./team_batting/'+str(i)+'.csv')
#     team_pitching(i).to_csv('./team_pitching/'+str(i)+'.csv')
#     team_fielding(i).to_csv('./team_fielding/'+str(i)+'.csv')
#     batting_stats(i).to_csv('./qualified_batting_stats/'+str(i)+'.csv')
#     pitching_stats(i).to_csv('./qualified_pitching_stats/'+str(i)+'.csv')
#     batting_stats(i, qual=0).to_csv('./all_batting_stats/'+str(i)+'.csv')
#     pitching_stats(i, qual=0).to_csv('./all_pitching_stats/'+str(i)+'.csv')
#     print(f"Generated CSVs for the {i} season")

# Loop through the csv generation every four hours

while True:

    team_batting(year).to_csv('./team_batting/'+str(year)+'.csv')
    team_pitching(year).to_csv('./team_pitching/'+str(year)+'.csv')
    team_fielding(year).to_csv('./team_fielding/'+str(year)+'.csv')
    batting_stats(year).to_csv('./qualified_batting_stats/'+str(year)+'.csv')
    pitching_stats(year).to_csv('./qualified_pitching_stats/'+str(year)+'.csv')
    batting_stats(year, qual=0).to_csv('./all_batting_stats/'+str(year)+'.csv')
    pitching_stats(year, qual=0).to_csv('./all_pitching_stats/'+str(year)+'.csv')

    sleep(14400)
