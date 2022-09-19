#!/usr/bin/env python3

# Parsing live data from Fangraphs

import requests
import bs4
from bs4 import BeautifulSoup
import pandas as pd
import pybaseball as pyb

# Find current year
import datetime
now = datetime.datetime.now()
year = now.year

# Import sleep time
from time import sleep

# Loop over everything using a for loop and sleep for an hour between each iteration

while True:

    qualified_live_batting=f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=y&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318&season={year}&month=33&season1={year}&ind=0&team=&rost=&age=0&filter=&players=&startdate=&enddate=&page=1_5000"
    qualified_live_pitching=f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=y&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318,319,320,321,322,323,324,325,326,327,328,329,330,331,332&season={year}&month=33&season1={year}&ind=0&team=0&rost=0&age=0&filter=&players=0&startdate=&enddate=&page=1_5000"
    all_live_batting=f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=0&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318&season={year}&month=33&season1={year}&ind=0&team=0&rost=0&age=0&filter=&players=0&startdate=&enddate=&page=1_5000"
    all_live_pitching=f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=0&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318,319,320,321,322,323,324,325,326,327,328,329,330,331,332&season={year}&month=33&season1={year}&ind=0&team=0&rost=0&age=0&filter=&players=0&startdate=&enddate=&page=1_5000"
#    live_team_batting=f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=0&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318&season={year}&month=33&season1={year}&ind=0&team=0,ts&rost=&age=0&filter=&players=0&startdate=&enddate="
#    live_team_pitching=f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=0&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318,319,320,321,322,323,324,325,326,327,328,329,330,331,332&season={year}&month=33&season1={year}&ind=0&team=0,ts&rost=0&age=0&filter=&players=0&startdate=&enddate="


    table_class="RadGrid RadGrid_FanGraphs"

    # Get the data from Fangraphs
    qualified_batting_data = requests.get(qualified_live_batting)
    qualified_pitching_data = requests.get(qualified_live_pitching)
    all_live_batting_data = requests.get(all_live_batting)
    all_live_pitching_data = requests.get(all_live_pitching)

    qualified_batting_soup = BeautifulSoup(qualified_batting_data.text, 'html.parser')
    qualified_pitching_soup = BeautifulSoup(qualified_pitching_data.text, 'html.parser')
    all_live_batting_soup = BeautifulSoup(all_live_batting_data.text, 'html.parser')
    all_live_pitching_soup = BeautifulSoup(all_live_pitching_data.text, 'html.parser')

    qualified_batting_table=qualified_batting_soup.find('table', {"id": "LeaderBoard1_dg1_ctl00"})
    qualified_pitching_table=qualified_pitching_soup.find('table', {"id": "LeaderBoard1_dg1_ctl00"})
    all_live_batting_table=all_live_batting_soup.find('table', {"id": "LeaderBoard1_dg1_ctl00"})
    all_live_pitching_table=all_live_pitching_soup.find('table', {"id": "LeaderBoard1_dg1_ctl00"})

    qualified_batting_df=pd.read_html(str(qualified_batting_table))[0]
    qualified_pitching_df=pd.read_html(str(qualified_pitching_table))[0]
    all_live_batting_df=pd.read_html(str(all_live_batting_table))[0]
    all_live_pitching_df=pd.read_html(str(all_live_pitching_table))[0]

    # Remove last row
    qualified_batting_df = qualified_batting_df.drop(qualified_batting_df.index[-1])
    qualified_pitching_df = qualified_pitching_df.drop(qualified_pitching_df.index[-1])
    all_live_batting_df = all_live_batting_df.drop(all_live_batting_df.index[-1])
    all_live_pitching_df = all_live_pitching_df.drop(all_live_pitching_df.index[-1])

    # Turn dataframe columns into list
    qualified_batting_df_columns = qualified_batting_df.columns.tolist()
    qualified_pitching_df_columns = qualified_pitching_df.columns.tolist()
    all_live_batting_df_columns = all_live_batting_df.columns.tolist()
    all_live_pitching_df_columns = all_live_pitching_df.columns.tolist()

    # split the data in the column tuple and only keep the second item in the list
    qualified_batting_df_columns = [x[1] for x in qualified_batting_df_columns]
    qualified_pitching_df_columns = [x[1] for x in qualified_pitching_df_columns]
    all_live_batting_df_columns = [x[1] for x in all_live_batting_df_columns]
    all_live_pitching_df_columns = [x[1] for x in all_live_pitching_df_columns]

    # assign new column names
    qualified_batting_df.columns = qualified_batting_df_columns
    qualified_pitching_df.columns = qualified_pitching_df_columns
    all_live_batting_df.columns = all_live_batting_df_columns
    all_live_pitching_df.columns = all_live_pitching_df_columns


    # remove first column
    qualified_batting_df = qualified_batting_df.drop(qualified_batting_df.columns[0], axis=1)
    qualified_pitching_df = qualified_pitching_df.drop(qualified_pitching_df.columns[0], axis=1)
    all_live_batting_df = all_live_batting_df.drop(all_live_batting_df.columns[0], axis=1)
    all_live_pitching_df = all_live_pitching_df.drop(all_live_pitching_df.columns[0], axis=1)

    # Clean up columns with %
    # Check is qualified_batting_df[column] contains % using str.contains
    # If it does, remove the % and convert the column to float
    for column in qualified_batting_df:
        if qualified_batting_df[column].str.contains('%').any():
            qualified_batting_df[column] = qualified_batting_df[column].str.replace('%', '').astype(float)
    for column in qualified_pitching_df:
        if qualified_pitching_df[column].str.contains('%').any():
            qualified_pitching_df[column] = qualified_pitching_df[column].str.replace('%', '').astype(float)
    for column in all_live_batting_df:
        if all_live_batting_df[column].str.contains('%').any():
            all_live_batting_df[column] = all_live_batting_df[column].str.replace('%', '').astype(float)
    for column in all_live_pitching_df:
        if all_live_pitching_df[column].str.contains('%').any():
            all_live_pitching_df[column] = all_live_pitching_df[column].str.replace('%', '').astype(float)


    # Pybaseball qualified batting stats

    pybaseball_qualified_batting_df = pyb.batting_stats(year)
    pybaseball_qualified_pitching_df = pyb.pitching_stats(year)
    pybaseball_all_pitching_df = pyb.pitching_stats(year, qual=0)
    pybaseball_all_batting_df = pyb.batting_stats(year, qual=0)

    null_columns=[]

    for column in qualified_batting_df:
        if qualified_batting_df[column].isnull().all():
            null_columns.append(column)

    # If column in null_columns, set qualified_batting_df[column] to pybaseball_qualified_batting_df[column] based on value in Name column

    for column in null_columns:
        for index, row in qualified_batting_df.iterrows():
            qualified_batting_df.loc[qualified_batting_df['Name'] == pybaseball_qualified_batting_df.loc[index, 'Name'], column] = pybaseball_qualified_batting_df.loc[index, column]

    # export to csv

    qualified_batting_df.to_csv(f"./qualified_batting_stats/{year}.csv", index=False)
    qualified_pitching_df.to_csv(f"./qualified_pitching_stats/{year}.csv", index=False)
    all_live_batting_df.to_csv(f"./all_batting_stats/{year}.csv", index=False)
    all_live_pitching_df.to_csv(f"./all_pitching_stats/{year}.csv", index=False)

    # sleep for an hour
    sleep(3600)
