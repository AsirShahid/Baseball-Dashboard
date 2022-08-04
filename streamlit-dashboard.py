#!/usr/bin/env python3

import matplotlib.pyplot as plt
import pybaseball as pyb
from pybaseball import team_batting
from pybaseball import team_pitching
from pybaseball import batting_stats
from pybaseball import pitching_stats
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
import pandas as pd
import numpy as np
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

pyb.cache.disable()

def getImage(path, zoom=0.055):
    return OffsetImage(plt.imread(path), zoom=zoom)

paths = [
    '/home/asir/Pictures/Logos/angels-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/orioles-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/redsox-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/whitesox-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/guardians-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/tigers-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/royals-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/twins-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/yankees-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/athletics-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/mariners-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/rays-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/rangers-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/bluejays-resizedmatplotlib.png',

    '/home/asir/Pictures/Logos/diamondbacks-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/braves-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/cubs-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/reds-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/rockies-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/marlins-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/astros-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/dodgers-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/brewers-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/nationals-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/mets-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/phillies-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/pirates-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/cardinals-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/padres-resizedmatplotlib.png',
    '/home/asir/Pictures/Logos/giants-resizedmatplotlib.png',
]

st.set_page_config(page_title="Baseball Stats", page_icon=":baseball:", layout="wide")

team_player=["Team", "Player"]

with st.sidebar:
    # Have user pick if they want team stats or player stats
    team_or_player = st.radio("", ["Team Stats", "Player Stats"])

# Is "Team" in team_or_player?
if "Team" in team_or_player:

    seasons=[]

    for i in range(2022,1997,-1):
        seasons.append(i)


    with st.sidebar:

        season = st.sidebar.selectbox("Select a season", seasons)

        logos_or_names = st.sidebar.radio("Do you want to see the logos or the names of the teams?", ["Logos", "Names"])

        batting_or_pitching_xaxis = st.radio("Do you want to see the batting or pitching stats on the x-axis?", ["Batting", "Pitching"])

        batting_or_pitching_yaxis = st.radio("Do you want to see the batting or pitching stats on the y-axis?", ["Batting", "Pitching"], 1)

    # Add season as a parameter to the url if it is used

    pitching=pd.read_csv(f"./team_pitching/{season}.csv")

    # If pitching["teamIDfg"] exists then sort by teamIDfg
    if "teamIDfg" in pitching.columns:
        pitching.sort_values(by="teamIDfg", inplace=True)

    batting=pd.read_csv(f"./team_batting/{season}.csv")
    # If batting["teamIDfg"] exists then sort by teamIDfg
    if "teamIDfg" in batting.columns:
        batting.sort_values(by="teamIDfg", inplace=True)

    # Remove first column
    pitching = pitching.drop(pitching.columns[0], axis=1)
    batting = batting.drop(batting.columns[0], axis=1)

    batting_cols=batting.columns.to_list()

    # If the columns exist then remove them
    if "WAR" in batting_cols:
        batting_cols.remove("WAR")

    batting_cols.insert(0, "WAR")

    if "Dol" in batting_cols:
        batting_cols.remove("Dol")
    if "Team" in batting_cols:
        batting_cols.remove("Team")
    if "Season" in batting_cols:
        batting_cols.remove("Season")

    pitching_cols=pitching.columns.to_list()

    if "WAR" in pitching_cols:
        pitching_cols.remove("WAR")

    pitching_cols.insert(0, "WAR")

    if "Dollars" in pitching_cols:
        pitching_cols.remove("Dollars")
    if "Team" in pitching_cols:
        pitching_cols.remove("Team")
    if "Season" in pitching_cols:
        pitching_cols.remove("Season")

    if batting_or_pitching_xaxis=="Batting":
        x_axis_stat_list=batting_cols
    if batting_or_pitching_xaxis=="Pitching":
        x_axis_stat_list=pitching_cols
    if batting_or_pitching_yaxis=="Batting":
        y_axis_stat_list=batting_cols
    if batting_or_pitching_yaxis=="Pitching":
        y_axis_stat_list=pitching_cols

    with st.sidebar:
        # Have user select the x-axis stat
        x_axis_stat = st.sidebar.selectbox("Select the x-axis stat", x_axis_stat_list)
        # Have user select the y-axis stat
        y_axis_stat = st.sidebar.selectbox("Select the y-axis stat", y_axis_stat_list)

        # Have user pick if they want vertical mean lines
        v_mean_line=st.sidebar.checkbox("Vertical mean line", True)

        # Have user pick if they want horizontal mean lines
        h_mean_line=st.sidebar.checkbox("Horizontal mean line", True)

    if batting_or_pitching_xaxis=="Batting":
        xaxis_stat=batting[x_axis_stat]
        zeros=[0]*len(batting)
    elif batting_or_pitching_xaxis=="Pitching":
        xaxis_stat=pitching[x_axis_stat]
        zeros=[0]*len(pitching)
    if batting_or_pitching_yaxis=="Batting":
        yaxis_stat=batting[y_axis_stat]
    elif batting_or_pitching_yaxis=="Pitching":
        yaxis_stat=pitching[y_axis_stat]


    if logos_or_names=="Logos":

        plt.figure(figsize=(50,50))
        fig, ax = plt.subplots()
        ax.scatter(xaxis_stat, yaxis_stat, s=0)

        for x0, y0, path in zip(xaxis_stat, yaxis_stat, paths):
            ab = AnnotationBbox(getImage(path), (x0, y0), frameon=False)
            ax.add_artist(ab)

        plt.title("Team Stats")

        plt.xlabel(f"{batting_or_pitching_xaxis} {x_axis_stat}")
        plt.ylabel(f"{batting_or_pitching_yaxis} {y_axis_stat}")


        if h_mean_line:
            plt.axhline(y=yaxis_stat.mean(), color='w', linestyle='--')
        if v_mean_line:
            plt.axvline(x=xaxis_stat.mean(), color='w', linestyle='--')

        plt.style.use("dark_background")

        plt.show()

        st.pyplot(plt)

    elif logos_or_names=="Names":

        fig = px.scatter(x=xaxis_stat, y=yaxis_stat, text=batting["Team"],
                         labels={"x": f"{batting_or_pitching_xaxis} {x_axis_stat}", "y": f"{batting_or_pitching_yaxis} {y_axis_stat}", "text": "Team"},
                         size=zeros)

        if h_mean_line:
            fig.add_hline(y=yaxis_stat.mean(), line_color='white', line_dash='dash')
        if v_mean_line:
            fig.add_vline(x=xaxis_stat.mean(), line_color='white', line_dash='dash')

        fig.update_layout(title="Team Stats", title_x=0.5)

        fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')
        fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')

        fig.update_layout(
            font=dict(
#                family="Courier New, monospace",
                size=22,
#                color="#7f7f7f"
            )
        )

        # Increase size of plotly graph
        # fig.update_layout(height=800, width=800)

        st.plotly_chart(fig, use_container_width=True, sharing="streamlit")



if "Player" in team_or_player:

    seasons=[]

    for i in range(2022,1870,-1):
        seasons.append(i)

    with st.sidebar:
        season = st.sidebar.selectbox("Select a season", seasons)

    batting=pd.read_csv(f"./qualified_batting_stats/{season}.csv")
    pitching=pd.read_csv(f"./qualified_pitching_stats/{season}.csv")
#    batting=batting.dropna(inplace=True, how="all")
#    pitching=pitching.dropna(inplace=True, how="all")

    # Remove first column
#    batting = batting.drop(batting.columns[0], axis=1)
#    pitching = pitching.drop(pitching.columns[0], axis=1)

    batting_cols=batting.columns.to_list()
    batting_cols.remove("WAR")
    batting_cols.remove("wRC+")
    batting_cols.insert(0, "WAR")
    batting_cols.insert(1, "wRC+")

    # If column exists, remove it
    if "Team" in batting_cols:
        batting_cols.remove("Team")
    if "Season" in batting_cols:
        batting_cols.remove("Season")
    if "Dollars" in batting_cols:
        batting_cols.remove("Dol")
    if "Name" in batting_cols:
        batting_cols.remove("Name")
    if "Season" in batting_cols:
        batting_cols.remove("Season")
    if "IDfg" in batting_cols:
        batting_cols.remove("IDfg")
    if "Unnamed: 0" in batting_cols:
        batting_cols.remove("Unnamed: 0")

    pitching_cols=pitching.columns.to_list()
    pitching_cols.remove("WAR")
    pitching_cols.remove("SIERA")
    pitching_cols.insert(0, "WAR")
    pitching_cols.insert(1, "SIERA")
    pitching_cols.remove("Dollars")
    #
    # If column exists, remove it
    if "Team" in batting_cols:
        batting_cols.remove("Team")
    if "Season" in batting_cols:
        batting_cols.remove("Season")
    if "Dollars" in batting_cols:
        batting_cols.remove("Dollars")
    if "Name" in batting_cols:
        batting_cols.remove("Name")
    if "Season" in batting_cols:
        batting_cols.remove("Season")
    if "IDfg" in batting_cols:
        batting_cols.remove("IDfg")
    if "Unnamed: 0" in batting_cols:
        batting_cols.remove("Unnamed: 0")

    min_pas=["Qualified"]
    # Append numbers from 0 to 700 going up by 10 to min_pas
    for i in range(0,700,10):
        min_pas.append(i)

    min_ip=["Qualified"]
    # Append numbers from 0 to 250 going up by 10 to min_ip
    for i in range(0,300,10):
        min_ip.append(i)


    batting["Name"]=batting["Name"].str.split(" ").str[0].str[0] + ". " + batting["Name"].str.split(" ").str[1]

    pitching["Name"]=pitching["Name"].str.split(" ").str[0].str[0] + ". " + pitching["Name"].str.split(" ").str[1]

    with st.sidebar:
        batters_or_pitchers=st.radio("Do you want to see the stats for batters or pitchers?", ["Batters", "Pitchers"])

#        only_qualified=st.sidebar.checkbox("Only show qualified players?", True)

#        if only_qualified:
#            if batters_or_pitchers=="Batters":
#                batting=batting_stats(season)
#            elif batters_or_pitchers=="Pitchers":
#                pitching=pitching_stats(season)

    if batters_or_pitchers=="Batters":

        with st.sidebar:
            xaxis_stat = st.sidebar.selectbox("Select a stat for the x-axis", batting_cols)
            yaxis_stat = st.sidebar.selectbox("Select a stat for the y-axis", batting_cols, 1)

            # Select Box for minimum PAs
            min_pa = st.sidebar.selectbox("Minimum PA", min_pas)

        if min_pa=="Qualified":

            teams_list=[]
            # Append all teams to teams_list
            # Sort teams alphabetically
            for i in batting["Team"].unique().tolist():
                teams_list.append(i)
            teams_list.sort()
            # Add "All Teams" to the top of the list
            teams_list.insert(0, "All Teams")
            # Remove - - - from teams_list
            teams_list.remove("- - -")

            # Allow user to select teams
            selected_team=st.sidebar.selectbox("Team:", teams_list)

            # If user selects "All Teams", show all teams
            # If user selects a team, show only that team
            if selected_team=="All Teams":
                batting=batting
            else:
                batting=batting[batting["Team"]==selected_team]
          

            zeros=[0]*len(batting)

            fig = px.scatter(x=batting[xaxis_stat], y=batting[yaxis_stat], text=batting["Name"], size=zeros,
                             labels={"x": f"{xaxis_stat}", "y": f"{yaxis_stat}"})

            # Increase size of x axis and y axis labels
            fig.update_xaxes(title=f"{xaxis_stat}", title_font=dict(size=22))
            fig.update_yaxes(title=f"{yaxis_stat}", title_font=dict(size=22))

            # Increase size of title
            fig.update_layout(title=f"{xaxis_stat} vs {yaxis_stat}", title_font=dict(size=26), title_x=0.5)

            fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')
            fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')

            st.plotly_chart(fig, use_container_width=True, sharing="streamlit")

        # If Not qualified, select batters with minimum PAs
        elif min_pa != "Qualified":
            batting=pd.read_csv(f"./all_batting_stats/{season}.csv")

            teams_list=[]
            # Append all teams to teams_list
            # Sort teams alphabetically
            for i in batting["Team"].unique().tolist():
                teams_list.append(i)
            teams_list.sort()
            # Add "All Teams" to the top of the list
            # Remove - - - from teams_list
            teams_list.remove("- - -")
            teams_list.insert(0, "All Teams")

            # Allow user to select teams
            selected_team=st.sidebar.selectbox("Team:", teams_list)

            # If user selects "All Teams", show all teams
            # If user selects a team, show only that team
            if selected_team=="All Teams":
                batting=batting
            else:
                batting=batting[batting["Team"]==selected_team]

            # remove first column
 #           batting = batting.drop(batting.columns[0], axis=1)

            # only keep batters with minimum PAs
            batting=batting[batting["PA"]>=min_pa]
            batting["Name"]=batting["Name"].str.split(" ").str[0].str[0] + ". " + batting["Name"].str.split(" ").str[1]

            zeros=[0]*len(batting)

            fig = px.scatter(x=batting[xaxis_stat], y=batting[yaxis_stat], text=batting["Name"], size=zeros,
                                labels={"x": f"{xaxis_stat}", "y": f"{yaxis_stat}"})


            fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')
            fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')

            st.plotly_chart(fig, use_container_width=True, sharing="streamlit")

    elif batters_or_pitchers =="Pitchers":

        with st.sidebar:
            xaxis_stat = st.sidebar.selectbox("Select a stat for the x-axis", pitching_cols)
            yaxis_stat = st.sidebar.selectbox("Select a stat for the y-axis", pitching_cols, 1)
            # Select Box for minimum IP
            min_ip = st.sidebar.selectbox("Minimum IP", min_ip)

        if min_ip=="Qualified":

            zeros=[0]*len(pitching)

            fig = px.scatter(x=pitching[xaxis_stat], y=pitching[yaxis_stat], text=pitching["Name"], size=zeros,
                            labels={"x": f"{xaxis_stat}", "y": f"{yaxis_stat}"})

            # Increase size of x axis and y axis labels
            fig.update_xaxes(title=f"{xaxis_stat}", title_font=dict(size=22))
            fig.update_yaxes(title=f"{yaxis_stat}", title_font=dict(size=22))

            # Increase size of title
            fig.update_layout(title=f"{xaxis_stat} vs {yaxis_stat}", title_font=dict(size=26), title_x=0.5)

            fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')
            fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')

            # Edit URL based on the selected

            st.plotly_chart(fig, use_container_width=True, sharing="streamlit")

        # If Not qualified, select pitchers with minimum IP
        elif min_ip != "Qualified":

            pitching=pd.read_csv(f"./all_pitching_stats/{season}.csv")
            # remove first column
#            pitching = pitching.drop(pitching.columns[0], axis=1)
            # only keep pitchers with minimum IP
            pitching=pitching[pitching["IP"]>=min_ip]
            pitching["Name"]=pitching["Name"].str.split(" ").str[0].str[0] + ". " + pitching["Name"].str.split(" ").str[1]

            zeros=[0]*len(pitching)

            fig = px.scatter(x=pitching[xaxis_stat], y=pitching[yaxis_stat], text=pitching["Name"], size=zeros,
                            labels={"x": f"{xaxis_stat}", "y": f"{yaxis_stat}"})

            # Increase size of x axis and y axis labels
            fig.update_xaxes(title=f"{xaxis_stat}", title_font=dict(size=22))
            fig.update_yaxes(title=f"{yaxis_stat}", title_font=dict(size=22))

            # Increase size of title
            fig.update_layout(title=f"{xaxis_stat} vs {yaxis_stat}", title_font=dict(size=26), title_x=0.5)

            fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')
            fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False, zerolinecolor='#3D3D3D')

            st.plotly_chart(fig, use_container_width=True, sharing="streamlit")


st.write("---")

st.markdown("""
    The data is provided by [pybaseball](https://pypi.org/project/pybaseball/)  and the plots are generated using [matplotlib](https://matplotlib.org/) and [plotly](https://plotly.com/python/).""")
