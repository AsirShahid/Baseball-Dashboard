#!/usr/bin/env python3
import pandas as pd
import requests
from bs4 import BeautifulSoup

batting="https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=y&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318&season=2022&month=0&season1=2022&ind=0&team=&rost=&age=&filter=&players=&page=1_10000"
pitching="https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=y&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318,319,320,321,322,323,324,325,326,327,328,329,330,331,332&season=2022&month=0&season1=2022&ind=0&team=0&rost=0&age=0&filter=&players=0&startdate=&enddate=&page=1_10000"

batting_team="https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=0&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318&season=2022&month=0&season1=2022&ind=0&team=0,ts&rost=&age=&filter=&players=0&startdate=&enddate="

pitching_team="https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=0&type=c,-1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225,226,227,228,229,230,231,232,233,234,235,236,237,238,239,240,241,242,243,244,245,246,247,248,249,250,251,252,253,254,255,256,257,258,259,260,261,262,263,264,265,266,267,268,269,270,271,272,273,274,275,276,277,278,279,280,281,282,283,284,285,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304,305,306,307,308,309,310,311,312,313,314,315,316,317,318,319,320,321,322,323,324,325,326,327,328,329,330,331,332&season=2022&month=0&season1=2022&ind=0&team=0,ts&rost=0&age=0&filter=&players=0&startdate=&enddate="

table_class="RadGrid RadGrid_FanGraphs"

batting_response=requests.get(batting)
pitching_response=requests.get(pitching)
batting_team_response=requests.get(batting_team)
pitching_team_response=requests.get(pitching_team)

batting_soup=BeautifulSoup(batting_response.text, 'html.parser')
pitching_soup=BeautifulSoup(pitching_response.text, 'html.parser')
batting_team_soup=BeautifulSoup(batting_team_response.text, 'html.parser')
pitching_team_soup=BeautifulSoup(pitching_team_response.text, 'html.parser')
#indiatable=soup.find('table', {'id': LeaderBoard1_dg1_ctl00})

# find table with id LeaderBoard1_dg1_ctl00
batting_table=batting_soup.find('table', {'id': 'LeaderBoard1_dg1_ctl00'})
pitching_table=pitching_soup.find('table', {'id': 'LeaderBoard1_dg1_ctl00'})
batting_team_table=batting_team_soup.find('table', {'id': 'LeaderBoard1_dg1_ctl00'})
pitching_team_table=pitching_team_soup.find('table', {'id': 'LeaderBoard1_dg1_ctl00'})

batting_df=pd.read_html(str(batting_table))[0]
pitching_df=pd.read_html(str(pitching_table))[0]
batting_team_df=pd.read_html(str(batting_team_table))[0]
pitching_team_df=pd.read_html(str(pitching_team_table))[0]

batting_df.drop(batting_df.index[-1], axis=0, inplace=True)
pitching_df.drop(pitching_df.index[-1], axis=0, inplace=True)
batting_team_df.drop(batting_team_df.index[-1], axis=0, inplace=True)
pitching_team_df.drop(pitching_team_df.index[-1], axis=0, inplace=True)
# print(pitching_df.columns)

# export to csv

# analyze data frame columns

# columns to list
batting_columns=batting_df.columns.tolist()

garbage=[]
new_columns=[]

for i in batting_columns:
    g, stat=i
    garbage.append(g)
    new_columns.append(stat)

batting_df.columns=new_columns

pitching_columns=pitching_df.columns.tolist()

garbage=[]
new_columns=[]

for i in pitching_columns:
    g, stat=i
    garbage.append(g)
    new_columns.append(stat)
    
pitching_df.columns=new_columns

batting_team_columns=batting_team_df.columns.tolist()

garbage=[]
new_columns=[]

for i in batting_team_columns:
    g, stat=i
    garbage.append(g)
    new_columns.append(stat)

batting_team_df.columns=new_columns

pitching_team_columns=pitching_team_df.columns.tolist()

garbage=[]
new_columns=[]

for i in pitching_team_columns:
    g, stat=i
    garbage.append(g)
    new_columns.append(stat)

pitching_team_df.columns=new_columns

# remove first column
batting_df.drop(batting_df.columns[0], axis=1, inplace=True)
pitching_df.drop(pitching_df.columns[0], axis=1, inplace=True)
batting_team_df.drop(batting_team_df.columns[0], axis=1, inplace=True)
pitching_team_df.drop(pitching_team_df.columns[0], axis=1, inplace=True)

# export to csv
batting_df.to_csv('batting_df.csv', index=False)
pitching_df.to_csv('pitching_df.csv', index=False)
batting_team_df.to_csv('batting_team_df.csv', index=False)
pitching_team_df.to_csv('pitching_team_df.csv', index=False)
