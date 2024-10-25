import matplotlib.pyplot as plt
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
import pandas as pd
import numpy as np
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import json
from pathlib import Path

# Load configuration
with open('config.json', 'r') as f:
    config = json.load(f)

st.set_page_config(page_title="Baseball Dashboard", page_icon=":baseball:", layout="wide")

# Custom CSS to improve sidebar appearance
st.markdown("""
<style>
    .sidebar .sidebar-content {
        background-image: linear-gradient(#2e7bcf,#2e7bcf);
        color: white;
    }
    .sidebar .sidebar-content .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    .sidebar .sidebar-content .stRadio > label {
        color: white;
        font-weight: bold;
    }
    .sidebar .sidebar-content .stSelectbox > label {
        color: white;
        font-weight: bold;
    }
    .sidebar .sidebar-content .stCheckbox > label {
        color: white;
    }
    .sidebar .sidebar-content .stExpander {
        background-color: rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        margin-bottom: 0.5rem;
    }
    .sidebar .sidebar-content .stExpander > div > div > div > div {
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_data(file_path):
    try:
        return pd.read_csv(file_path)
    except FileNotFoundError:
        st.error(f"File not found: {file_path}")
        return pd.DataFrame()

def getImage(path, zoom=0.055):
    return OffsetImage(plt.imread(path), zoom=zoom)

paths = [Path(f"./Logos/{team}-resizedmatplotlib.png") for team in [
    'angels', 'orioles', 'redsox', 'whitesox', 'guardians', 'tigers', 'royals', 'twins', 'yankees',
    'athletics', 'mariners', 'rays', 'rangers', 'bluejays', 'diamondbacks', 'braves', 'cubs', 'reds',
    'rockies', 'marlins', 'astros', 'dodgers', 'brewers', 'nationals', 'mets', 'phillies', 'pirates',
    'cardinals', 'padres', 'giants'
]]

def process_columns(columns):
    cols = columns.tolist()
    for col in ["WAR", "wRC+", "SIERA"]:
        if col in cols:
            cols.remove(col)
            cols.insert(0, col)
    for col in ["Team", "Season", "Dollars", "Name", "IDfg", "Unnamed: 0"]:
        if col in cols:
            cols.remove(col)
    return cols

def get_query_param(name, default=None):
    """Get a query parameter value, returning the default if not found"""
    return st.query_params.get(name, default)

def main():
    st.title("Baseball Statistics Dashboard")

    with st.sidebar:
        st.header("Dashboard Controls")
        view_option = st.radio("Select View", ["Team Stats", "Player Stats"], 
                             index=0 if get_query_param("view") != "Player Stats" else 1,
                             help="Choose between team or player statistics")
        st.query_params["view"] = view_option

    if view_option == "Team Stats":
        team_stats()
    else:
        player_stats()

def team_stats():
    seasons = list(range(config['current_year'], 1997, -1))
    
    # Get initial values from URL parameters
    initial_season = int(get_query_param("season", seasons[0]))
    initial_display = get_query_param("display", "Logos")
    initial_x_type = get_query_param("x_type", "Batting")
    initial_y_type = get_query_param("y_type", "Pitching")

    with st.sidebar:
        with st.expander("🔧 General Settings", expanded=True):
            season = st.selectbox("Select Season", seasons, 
                                index=seasons.index(initial_season),
                                help="Choose the season for which you want to view statistics")
            logos_or_names = st.radio("Display Teams As", ["Logos", "Names"], 
                                    index=0 if initial_display == "Logos" else 1,
                                    help="Choose how teams should be represented on the plot")

        with st.expander("📊 Axis Settings", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                batting_or_pitching_xaxis = st.radio("X-axis Stats", ["Batting", "Pitching"], 
                                                   index=0 if initial_x_type == "Batting" else 1,
                                                   help="Select the type of statistics for the X-axis")
            with col2:
                batting_or_pitching_yaxis = st.radio("Y-axis Stats", ["Batting", "Pitching"], 
                                                   index=0 if initial_y_type == "Batting" else 1,
                                                   help="Select the type of statistics for the Y-axis")

    # Update URL parameters
    st.query_params.update({
        "season": season,
        "display": logos_or_names,
        "x_type": batting_or_pitching_xaxis,
        "y_type": batting_or_pitching_yaxis
    })

    pitching = load_data(f"{config['team_pitching_dir']}/{season}.csv")
    batting = load_data(f"{config['team_batting_dir']}/{season}.csv")

    if pitching.empty or batting.empty:
        st.error("Failed to load data. Please check your data files.")
        return

    pitching = pitching.sort_values(by="teamIDfg") if "teamIDfg" in pitching.columns else pitching
    batting = batting.sort_values(by="teamIDfg") if "teamIDfg" in batting.columns else batting

    batting_cols = process_columns(batting.columns)
    pitching_cols = process_columns(pitching.columns)

    x_axis_stat_list = batting_cols if batting_or_pitching_xaxis == "Batting" else pitching_cols
    y_axis_stat_list = batting_cols if batting_or_pitching_yaxis == "Batting" else pitching_cols

    # Get initial stat selections from URL parameters
    initial_x_stat = get_query_param("x_stat", x_axis_stat_list[0])
    initial_y_stat = get_query_param("y_stat", y_axis_stat_list[0])

    with st.sidebar:
        with st.expander("📈 Plot Settings", expanded=True):
            x_axis_stat = st.selectbox("X-axis Stat", x_axis_stat_list, 
                                     index=x_axis_stat_list.index(initial_x_stat) if initial_x_stat in x_axis_stat_list else 0,
                                     help="Choose the statistic for the X-axis")
            y_axis_stat = st.selectbox("Y-axis Stat", y_axis_stat_list,
                                     index=y_axis_stat_list.index(initial_y_stat) if initial_y_stat in y_axis_stat_list else 0,
                                     help="Choose the statistic for the Y-axis")
            v_mean_line = st.checkbox("Show Vertical Mean Line", True, help="Display a vertical line at the mean X value")
            h_mean_line = st.checkbox("Show Horizontal Mean Line", True, help="Display a horizontal line at the mean Y value")

    # Update URL parameters for stats
    st.query_params.update({
        "x_stat": x_axis_stat,
        "y_stat": y_axis_stat
    })

    xaxis_stat = batting[x_axis_stat] if batting_or_pitching_xaxis == "Batting" else pitching[x_axis_stat]
    yaxis_stat = batting[y_axis_stat] if batting_or_pitching_yaxis == "Batting" else pitching[y_axis_stat]

    if logos_or_names == "Logos":
        plot_team_logos(xaxis_stat, yaxis_stat, x_axis_stat, y_axis_stat, batting_or_pitching_xaxis, batting_or_pitching_yaxis, v_mean_line, h_mean_line)
    else:
        plot_team_names(xaxis_stat, yaxis_stat, x_axis_stat, y_axis_stat, batting_or_pitching_xaxis, batting_or_pitching_yaxis, v_mean_line, h_mean_line, batting)

def player_stats():
    seasons = list(range(config['current_year'], 1870, -1))
    
    initial_season = int(get_query_param("season", seasons[0]))
    initial_type = get_query_param("player_type", "Batters")

    with st.sidebar:
        with st.expander("🔧 General Settings", expanded=True):
            season = st.selectbox("Select Season", seasons,
                                index=seasons.index(initial_season),
                                help="Choose the season for which you want to view statistics")
            batters_or_pitchers = st.radio("Stats Type", ["Batters", "Pitchers"],
                                         index=0 if initial_type == "Batters" else 1,
                                         help="Choose between batting or pitching statistics")

    st.query_params.update({
        "season": season,
        "player_type": batters_or_pitchers
    })

    if batters_or_pitchers == "Batters":
        player_batting_stats(season)
    else:
        player_pitching_stats(season)

def player_batting_stats(season):
    batting = load_data(f"{config['qualified_batting_dir']}/{season}.csv")
    if batting.empty:
        st.error("Failed to load batting data. Please check your data files.")
        return

    batting["WAR/650 PAs"] = (batting["WAR"] / batting["PA"] * 650).round(2)
    batting_cols = process_columns(batting.columns)

    min_pas = ["Qualified"] + list(range(0, 700, 10))
    
    initial_x_stat = get_query_param("x_stat", batting_cols[0])
    initial_y_stat = get_query_param("y_stat", batting_cols[1])
    initial_min_pa = get_query_param("min_pa", "Qualified")

    with st.sidebar:
        with st.expander("📊 Plot Settings", expanded=True):
            xaxis_stat = st.selectbox("X-axis Stat", batting_cols,
                                    index=batting_cols.index(initial_x_stat) if initial_x_stat in batting_cols else 0,
                                    help="Choose the statistic for the X-axis")
            yaxis_stat = st.selectbox("Y-axis Stat", batting_cols,
                                    index=batting_cols.index(initial_y_stat) if initial_y_stat in batting_cols else 1,
                                    help="Choose the statistic for the Y-axis")
            min_pa = st.selectbox("Minimum PA", min_pas,
                                index=min_pas.index(initial_min_pa) if initial_min_pa in min_pas else 0,
                                help="Set the minimum number of plate appearances")

    st.query_params.update({
        "x_stat": xaxis_stat,
        "y_stat": yaxis_stat,
        "min_pa": min_pa
    })

    batting, selected_team = filter_data(batting, min_pa)

    plot_player_stats(batting, xaxis_stat, yaxis_stat, "Batting")

def player_pitching_stats(season):
    pitching = load_data(f"{config['qualified_pitching_dir']}/{season}.csv")
    if pitching.empty:
        st.error("Failed to load pitching data. Please check your data files.")
        return

    pitching_cols = process_columns(pitching.columns)

    min_ip = ["Qualified"] + list(range(0, 300, 10))
    
    initial_x_stat = get_query_param("x_stat", pitching_cols[0])
    initial_y_stat = get_query_param("y_stat", pitching_cols[1])
    initial_min_ip = get_query_param("min_ip", "Qualified")

    with st.sidebar:
        with st.expander("📊 Plot Settings", expanded=True):
            xaxis_stat = st.selectbox("X-axis Stat", pitching_cols,
                                    index=pitching_cols.index(initial_x_stat) if initial_x_stat in pitching_cols else 0,
                                    help="Choose the statistic for the X-axis")
            yaxis_stat = st.selectbox("Y-axis Stat", pitching_cols,
                                    index=pitching_cols.index(initial_y_stat) if initial_y_stat in pitching_cols else 1,
                                    help="Choose the statistic for the Y-axis")
            min_ip_value = st.selectbox("Minimum IP", min_ip,
                                      index=min_ip.index(initial_min_ip) if initial_min_ip in min_ip else 0,
                                      help="Set the minimum number of innings pitched")

    st.query_params.update({
        "x_stat": xaxis_stat,
        "y_stat": yaxis_stat,
        "min_ip": min_ip_value
    })

    pitching, selected_team = filter_data(pitching, min_ip_value, "IP")

    plot_player_stats(pitching, xaxis_stat, yaxis_stat, "Pitching")

def filter_data(data, min_value, column="PA"):
    teams_list = sorted(data["Team"].unique().tolist())
    teams_list = ["All Teams", "AL", "NL"] + teams_list
    if "- - -" in teams_list:
        teams_list.remove("- - -")

    initial_team = get_query_param("team", "All Teams")
    selected_team = st.sidebar.selectbox("Team:", teams_list,
                                       index=teams_list.index(initial_team) if initial_team in teams_list else 0,
                                       help="Filter players by team")
    
    st.query_params["team"] = selected_team

    if min_value != "Qualified":
        data = load_data(f"{config['all_batting_dir'] if column == 'PA' else config['all_pitching_dir']}/{data['Season'].iloc[0]}.csv")
        data = data[data[column] >= min_value]

    if selected_team == "All Teams":
        pass
    elif selected_team == "NL":
        data = data[data["Team"].isin(["ARI", "ATL", "CHC", "CIN", "COL", "LAD", "MIA", "MIL", "NYM", "PHI", "PIT", "SDP", "SFG", "STL", "WAS"])]
    elif selected_team == "AL":
        data = data[data["Team"].isin(["BAL", "BOS", "CHW", "CLE", "DET", "HOU", "LAA", "KCR", "MIN", "NYY", "OAK", "SEA", "TOR", "TEX", "TOR"])]
    else:
        data = data[data["Team"] == selected_team]

    data["Name"] = data["Name"].str.split(" ").str[0].str[0] + ". " + data["Name"].str.split(" ").str[1]
    return data, selected_team

def plot_team_logos(xaxis_stat, yaxis_stat, x_axis_stat, y_axis_stat, batting_or_pitching_xaxis, batting_or_pitching_yaxis, v_mean_line, h_mean_line):
    plt.figure(figsize=(50, 50))
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
    st.pyplot(plt)

def plot_team_names(xaxis_stat, yaxis_stat, x_axis_stat, y_axis_stat, batting_or_pitching_xaxis, batting_or_pitching_yaxis, v_mean_line, h_mean_line, batting):
    fig = px.scatter(x=xaxis_stat, y=yaxis_stat, text=batting["Team"],
                     labels={"x": f"{batting_or_pitching_xaxis} {x_axis_stat}", "y": f"{batting_or_pitching_yaxis} {y_axis_stat}", "text": "Team"},
                     size=[0]*len(batting))

    if h_mean_line:
        fig.add_hline(y=yaxis_stat.mean(), line_color='white', line_dash='dash')
    if v_mean_line:
        fig.add_vline(x=xaxis_stat.mean(), line_color='white', line_dash='dash')

    fig.update_layout(title="Team Stats", title_x=0.5, font=dict(size=22))
    fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False)
    fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False)

    st.plotly_chart(fig, use_container_width=True)

def plot_player_stats(data, xaxis_stat, yaxis_stat, stat_type):
    fig = px.scatter(x=data[xaxis_stat], y=data[yaxis_stat], text=data["Name"],
                     labels={"x": f"{xaxis_stat}", "y": f"{yaxis_stat}"},
                     size=[0]*len(data))

    fig.update_xaxes(title=f"{xaxis_stat}", title_font=dict(size=22))
    fig.update_yaxes(title=f"{yaxis_stat}", title_font=dict(size=22))
    fig.update_layout(title=f"{xaxis_stat} vs {yaxis_stat}", title_font=dict(size=26), title_x=0.5)
    fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False)
    fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='#3D3D3D', zeroline=False)

    st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()

st.write("---")
st.markdown(f"""
    The data is provided by [Fangraphs](https://www.fangraphs.com/) and processed using [pybaseball](https://pypi.org/project/pybaseball/).
    The plots are generated using [matplotlib](https://matplotlib.org/) and [plotly](https://plotly.com/python/).
    Data is current as of the {config['current_year']} season.
""")
