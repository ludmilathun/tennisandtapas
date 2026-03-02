import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json
import os
import random
from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional
from itertools import combinations
import copy

# Data file for persistence
DATA_FILE = "tennis_tapas_data.json"

# Admin PIN for protected actions
ADMIN_PIN = "4321"


@dataclass
class Player:
    name: str
    rating: int
    games_sat_out: int = 0
    last_partners: List[str] = None
    last_opponents: List[str] = None

    def __post_init__(self):
        if self.last_partners is None:
            self.last_partners = []
        if self.last_opponents is None:
            self.last_opponents = []


@dataclass
class Match:
    court_number: int
    is_singles: bool
    team1: List[str]
    team2: List[str]
    team1_avg_rating: float
    team2_avg_rating: float


def load_data():
    """Load data from file for persistence."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return {
        "players": {},
        "num_courts": 2,
        "current_round": 0,
        "current_matches": [],
        "round_history": [],
        "confirmed": False
    }


def save_data(data):
    """Save data to file for persistence."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_player_rating(players: dict, name: str) -> int:
    """Get a player's rating."""
    return players.get(name, {}).get("rating", 5)


def calculate_team_avg(players: dict, team: List[str]) -> float:
    """Calculate average rating of a team."""
    if not team:
        return 0
    return sum(get_player_rating(players, p) for p in team) / len(team)


def had_recent_pairing(players: dict, p1: str, p2: str, as_partners: bool) -> bool:
    """Check if two players were recently paired together or against each other."""
    player1 = players.get(p1, {})
    if as_partners:
        return p2 in player1.get("last_partners", [])
    else:
        return p2 in player1.get("last_opponents", [])


def score_match(players: dict, team1: List[str], team2: List[str], is_singles: bool) -> float:
    """
    Score a potential match. Lower is better.
    Considers: rating balance, avoiding repeats, sat-out priority.
    """
    score = 0

    # Rating balance (most important)
    avg1 = calculate_team_avg(players, team1)
    avg2 = calculate_team_avg(players, team2)
    rating_diff = abs(avg1 - avg2)
    score += rating_diff * 10

    # Penalize if rating difference > 1
    if rating_diff > 1:
        score += (rating_diff - 1) * 20

    # Penalize recent pairings
    all_players = team1 + team2

    # Check partners (within same team)
    if not is_singles:
        if had_recent_pairing(players, team1[0], team1[1], as_partners=True):
            score += 5
        if had_recent_pairing(players, team2[0], team2[1], as_partners=True):
            score += 5

    # Check opponents
    for p1 in team1:
        for p2 in team2:
            if had_recent_pairing(players, p1, p2, as_partners=False):
                score += 3

    # Prioritize players who sat out (negative score = good)
    for p in all_players:
        sat_out = players.get(p, {}).get("games_sat_out", 0)
        score -= sat_out * 2

    return score


def generate_matches(players: dict, num_courts: int) -> Tuple[List[Match], List[str]]:
    """Generate optimal matches for the given players and courts."""
    # Exclude paused players from available pool
    available_players = [p for p in players.keys() if not players.get(p, {}).get("paused", False)]
    
    if len(available_players) < 2:
        return [], available_players

    matches = []
    used_players = set()

    # Separate players who sat out (must play) from others
    must_play = [p for p in available_players if players.get(p, {}).get("games_sat_out", 0) > 0]
    others = [p for p in available_players if p not in must_play]
    random.shuffle(others)
    
    # Sort must_play by how many times they sat out (most sat out first)
    must_play.sort(key=lambda p: players.get(p, {}).get("games_sat_out", 0), reverse=True)

    # Calculate total spots available
    max_spots = num_courts * 4  # Maximum if all doubles
    
    # Determine court allocation based on total players
    total_players = len(available_players)
    max_doubles_courts = total_players // 4
    remaining_after_doubles = total_players - (max_doubles_courts * 4)

    if max_doubles_courts >= num_courts:
        doubles_courts = num_courts
        singles_courts = 0
        total_spots = num_courts * 4
    else:
        doubles_courts = max_doubles_courts
        if remaining_after_doubles >= 2:
            singles_courts = min(num_courts - doubles_courts, remaining_after_doubles // 2)
        else:
            singles_courts = 0
        total_spots = doubles_courts * 4 + singles_courts * 2

    # Build priority list: must_play players first, then others
    # This guarantees players who sat out will be included
    priority_players = must_play + others
    
    # Select players who will play this round
    players_this_round = priority_players[:total_spots]
    random.shuffle(players_this_round)

    court_number = 1

    # Generate doubles matches
    for _ in range(doubles_courts):
        available = [p for p in players_this_round if p not in used_players]
        if len(available) < 4:
            break

        best_match = None
        best_score = float('inf')

        # Try different combinations to find optimal match
        for team1_combo in combinations(available[:12], 2):
            remaining = [p for p in available if p not in team1_combo][:10]
            for team2_combo in combinations(remaining, 2):
                team1 = list(team1_combo)
                team2 = list(team2_combo)
                score = score_match(players, team1, team2, is_singles=False)
                if score < best_score:
                    best_score = score
                    best_match = (team1, team2)

        if best_match:
            team1, team2 = best_match
            avg1 = calculate_team_avg(players, team1)
            avg2 = calculate_team_avg(players, team2)
            matches.append(Match(
                court_number=court_number,
                is_singles=False,
                team1=team1,
                team2=team2,
                team1_avg_rating=round(avg1, 1),
                team2_avg_rating=round(avg2, 1)
            ))
            used_players.update(team1 + team2)
            court_number += 1

    # Generate singles matches
    for _ in range(singles_courts):
        available = [p for p in players_this_round if p not in used_players]
        if len(available) < 2:
            break

        best_match = None
        best_score = float('inf')

        for combo in combinations(available[:8], 2):
            p1, p2 = combo
            score = score_match(players, [p1], [p2], is_singles=True)
            if score < best_score:
                best_score = score
                best_match = (p1, p2)

        if best_match:
            p1, p2 = best_match
            r1 = get_player_rating(players, p1)
            r2 = get_player_rating(players, p2)
            matches.append(Match(
                court_number=court_number,
                is_singles=True,
                team1=[p1],
                team2=[p2],
                team1_avg_rating=float(r1),
                team2_avg_rating=float(r2)
            ))
            used_players.add(p1)
            used_players.add(p2)
            court_number += 1

    waiting = [p for p in available_players if p not in used_players]
    return matches, waiting


def update_player_history(players: dict, matches: List[dict]):
    """Update player history after confirming a round."""
    for match in matches:
        team1 = match["team1"]
        team2 = match["team2"]
        is_singles = match["is_singles"]

        # Update partners (for doubles)
        if not is_singles:
            for p in team1:
                if p in players:
                    players[p]["last_partners"] = [t for t in team1 if t != p]
            for p in team2:
                if p in players:
                    players[p]["last_partners"] = [t for t in team2 if t != p]

        # Update opponents
        for p in team1:
            if p in players:
                players[p]["last_opponents"] = team2.copy()
        for p in team2:
            if p in players:
                players[p]["last_opponents"] = team1.copy()

        # Reset sat out counter for players who played
        for p in team1 + team2:
            if p in players:
                players[p]["games_sat_out"] = 0


def update_waiting_players(players: dict, waiting: List[str]):
    """Increment sat out counter for waiting players."""
    for p in waiting:
        if p in players:
            players[p]["games_sat_out"] = players[p].get("games_sat_out", 0) + 1


def match_to_dict(match: Match) -> dict:
    """Convert Match object to dictionary."""
    return {
        "court_number": match.court_number,
        "is_singles": match.is_singles,
        "team1": match.team1,
        "team2": match.team2,
        "team1_avg_rating": match.team1_avg_rating,
        "team2_avg_rating": match.team2_avg_rating
    }


# Page configuration
st.set_page_config(
    page_title="Tennis & Tapas Toss",
    page_icon="🎾",
    layout="wide"
)

# Auto-refresh every 10 seconds for live updates across devices
st_autorefresh(interval=10000, limit=None, key="data_refresh")

# Custom CSS
st.markdown("""
<style>
    .main-title {
        text-align: center;
        color: #2E7D32;
        font-size: 3rem;
        margin-bottom: 0;
    }
    .subtitle {
        text-align: center;
        color: #666;
        font-size: 1.2rem;
        margin-top: 0;
    }
    .court-card {
        background: linear-gradient(135deg, #4CAF50 0%, #2E7D32 100%);
        padding: 20px;
        border-radius: 15px;
        color: white;
        margin: 10px 0;
    }
    .waiting-card {
        background: linear-gradient(135deg, #FF9800 0%, #F57C00 100%);
        padding: 15px;
        border-radius: 10px;
        color: white;
    }
    .player-badge {
        background: rgba(255,255,255,0.2);
        padding: 5px 10px;
        border-radius: 20px;
        margin: 2px;
        display: inline-block;
    }
    .vs-text {
        font-size: 1.5rem;
        font-weight: bold;
        text-align: center;
    }
    .round-indicator {
        background: #1976D2;
        color: white;
        padding: 10px 20px;
        border-radius: 25px;
        font-size: 1.2rem;
        text-align: center;
        margin: 20px auto;
        width: fit-content;
    }
</style>
""", unsafe_allow_html=True)

# Load persisted data
data = load_data()

# Initialize session state from persisted data
if "initialized" not in st.session_state:
    st.session_state.players = data.get("players", {})
    st.session_state.num_courts = data.get("num_courts", 2)
    st.session_state.current_round = data.get("current_round", 0)
    st.session_state.current_matches = data.get("current_matches", [])
    st.session_state.waiting_players = data.get("waiting_players", [])
    st.session_state.round_history = data.get("round_history", [])
    st.session_state.confirmed = data.get("confirmed", False)
    st.session_state.editing_matches = None
    st.session_state.is_admin = False
    st.session_state.initialized = True


def persist_state():
    """Save current session state to file."""
    save_data({
        "players": st.session_state.players,
        "num_courts": st.session_state.num_courts,
        "current_round": st.session_state.current_round,
        "current_matches": st.session_state.current_matches,
        "waiting_players": st.session_state.waiting_players,
        "round_history": st.session_state.round_history,
        "confirmed": st.session_state.confirmed
    })


# Title
st.markdown('<h1 class="main-title">🎾 Tennis & Tapas Toss 🍷</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Organize your tennis matches with ease!</p>', unsafe_allow_html=True)

st.divider()

# Sidebar for configuration and player management
with st.sidebar:
    st.header("⚙️ Configuration")

    # Admin PIN section
    st.subheader("🔐 Admin Access")
    if st.session_state.is_admin:
        st.success("✓ Admin mode active")
        if st.button("Lock Admin", use_container_width=True):
            st.session_state.is_admin = False
            st.rerun()
    else:
        pin_input = st.text_input("Enter PIN for admin access", type="password", key="pin_input")
        if st.button("Unlock", use_container_width=True):
            if pin_input == ADMIN_PIN:
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("Incorrect PIN")
    
    st.divider()

    # Number of courts (Admin only)
    if st.session_state.is_admin:
        new_num_courts = st.number_input(
            "Number of Courts",
            min_value=1,
            max_value=20,
            value=st.session_state.num_courts,
            key="courts_input"
        )
        if new_num_courts != st.session_state.num_courts:
            st.session_state.num_courts = new_num_courts
            persist_state()
    else:
        st.metric("Number of Courts", st.session_state.num_courts)
        st.caption("🔒 Admin can change this")

    st.divider()

    # Add player section
    st.header("➕ Add Player")
    with st.form("add_player_form", clear_on_submit=True):
        new_name = st.text_input("Player Name")
        new_rating = st.slider("Rating (1-9)", min_value=1, max_value=9, value=5)
        submitted = st.form_submit_button("Add Player", use_container_width=True)

        if submitted and new_name.strip():
            name = new_name.strip()
            if name in st.session_state.players:
                st.error(f"Player '{name}' already exists!")
            else:
                st.session_state.players[name] = {
                    "name": name,
                    "rating": new_rating,
                    "games_sat_out": 0,
                    "paused": False,
                    "last_partners": [],
                    "last_opponents": []
                }
                persist_state()
                st.success(f"Added {name} (Rating: {new_rating})")
                st.rerun()

    st.divider()

    # Reset button (Admin only)
    st.header("🔄 Reset")
    if st.session_state.is_admin:
        if st.button("🗑️ Reset Everything", use_container_width=True, type="secondary"):
            st.session_state.players = {}
            st.session_state.current_round = 0
            st.session_state.current_matches = []
            st.session_state.waiting_players = []
            st.session_state.round_history = []
            st.session_state.confirmed = False
            st.session_state.editing_matches = None
            persist_state()
            st.rerun()
    else:
        st.info("🔒 Admin access required")

# Main content area
col1, col2 = st.columns([1, 2])

# Player list
with col1:
    st.header("👥 Players")
    active_players = sum(1 for p in st.session_state.players.values() if not p.get("paused", False))
    st.caption(f"Active: {active_players} / {len(st.session_state.players)} players | Court capacity: {st.session_state.num_courts * 4} (doubles)")

    if not st.session_state.players:
        st.info("No players added yet. Add players using the sidebar.")
    else:
        # Sort players: active first (sorted by rating), then paused
        sorted_players = sorted(
            st.session_state.players.items(),
            key=lambda x: (x[1].get("paused", False), -x[1]["rating"])
        )

        for name, player in sorted_players:
            is_paused = player.get("paused", False)
            sat_out = player.get("games_sat_out", 0)
            
            col_name, col_rating, col_pause, col_remove = st.columns([2.5, 0.8, 1, 0.7])
            with col_name:
                status = "⏸️ " if is_paused else ""
                sat_indicator = "🔴 " if sat_out > 0 and not is_paused else ""
                st.write(f"{status}{sat_indicator}**{name}**")
            with col_rating:
                st.write(f"⭐{player['rating']}")
            with col_pause:
                pause_label = "▶️" if is_paused else "⏸️"
                pause_help = "Resume playing" if is_paused else "Pause (skip rounds)"
                if st.button(pause_label, key=f"pause_{name}", help=pause_help):
                    st.session_state.players[name]["paused"] = not is_paused
                    persist_state()
                    st.rerun()
            with col_remove:
                if st.button("❌", key=f"remove_{name}", help=f"Remove {name}"):
                    del st.session_state.players[name]
                    st.session_state.current_matches = []
                    st.session_state.waiting_players = []
                    st.session_state.confirmed = False
                    persist_state()
                    st.rerun()

        # Legend
        active_count = sum(1 for p in st.session_state.players.values() if not p.get("paused", False))
        paused_count = len(st.session_state.players) - active_count
        st.caption(f"Active: {active_count} | Paused: {paused_count}")
        if any(p.get("games_sat_out", 0) > 0 for p in st.session_state.players.values()):
            st.caption("🔴 = Sat out last round (priority)")

# Match area
with col2:
    st.header("🏟️ Courts")

    # Round indicator
    if st.session_state.current_round > 0:
        st.markdown(f'<div class="round-indicator">Round {st.session_state.current_round}</div>', unsafe_allow_html=True)

    # Generate/Confirm buttons (Admin only)
    active_count = sum(1 for p in st.session_state.players.values() if not p.get("paused", False))
    if active_count >= 2:
        if st.session_state.is_admin:
            btn_col1, btn_col2, btn_col3 = st.columns(3)

            with btn_col1:
                if st.button("🎲 Generate Round", use_container_width=True, type="primary"):
                    matches, waiting = generate_matches(
                        st.session_state.players,
                        st.session_state.num_courts
                    )
                    st.session_state.current_matches = [match_to_dict(m) for m in matches]
                    st.session_state.waiting_players = waiting
                    st.session_state.confirmed = False
                    st.session_state.editing_matches = None
                    persist_state()
                    st.rerun()

            with btn_col2:
                if st.session_state.current_matches and not st.session_state.confirmed:
                    if st.button("✅ Confirm Round", use_container_width=True, type="secondary"):
                        st.session_state.current_round += 1
                        st.session_state.confirmed = True

                        # Update player history
                        update_player_history(
                            st.session_state.players,
                            st.session_state.current_matches
                        )

                        # Update waiting players' sat out count
                        update_waiting_players(
                            st.session_state.players,
                            st.session_state.waiting_players
                        )

                        # Add to history
                        st.session_state.round_history.append({
                            "round": st.session_state.current_round,
                            "matches": st.session_state.current_matches.copy(),
                            "waiting": st.session_state.waiting_players.copy()
                        })

                        persist_state()
                        st.rerun()

            with btn_col3:
                if st.session_state.current_matches and not st.session_state.confirmed:
                    editing = st.session_state.editing_matches is not None
                    if st.button(
                        "💾 Save Edits" if editing else "✏️ Edit Matches",
                        use_container_width=True
                    ):
                        if editing:
                            st.session_state.editing_matches = None
                        else:
                            st.session_state.editing_matches = copy.deepcopy(st.session_state.current_matches)
                        st.rerun()
        else:
            st.info("🔒 Enter admin PIN in sidebar to generate rounds")

    # Display matches
    if st.session_state.current_matches:
        status_text = "✅ Confirmed" if st.session_state.confirmed else "⏳ Pending Confirmation"
        st.caption(status_text)

        # Check if we're in edit mode
        if st.session_state.editing_matches is not None and not st.session_state.confirmed:
            st.info("📝 Edit mode: Swap players between positions using the dropdowns below")

            all_playing = []
            for m in st.session_state.current_matches:
                all_playing.extend(m["team1"])
                all_playing.extend(m["team2"])
            all_playing.extend(st.session_state.waiting_players)

            for i, match in enumerate(st.session_state.current_matches):
                with st.container():
                    match_type = "Singles" if match["is_singles"] else "Doubles"
                    st.subheader(f"Court {match['court_number']} ({match_type})")

                    if match["is_singles"]:
                        col_t1, col_vs, col_t2 = st.columns([2, 1, 2])
                        with col_t1:
                            new_p1 = st.selectbox(
                                "Player 1",
                                options=all_playing,
                                index=all_playing.index(match["team1"][0]) if match["team1"][0] in all_playing else 0,
                                key=f"edit_m{i}_t1_p1"
                            )
                            st.session_state.current_matches[i]["team1"] = [new_p1]
                        with col_vs:
                            st.markdown("<br><center><b>VS</b></center>", unsafe_allow_html=True)
                        with col_t2:
                            new_p2 = st.selectbox(
                                "Player 2",
                                options=all_playing,
                                index=all_playing.index(match["team2"][0]) if match["team2"][0] in all_playing else 0,
                                key=f"edit_m{i}_t2_p1"
                            )
                            st.session_state.current_matches[i]["team2"] = [new_p2]
                    else:
                        col_t1, col_vs, col_t2 = st.columns([2, 1, 2])
                        with col_t1:
                            st.write("**Team 1**")
                            new_t1_p1 = st.selectbox(
                                "Player 1",
                                options=all_playing,
                                index=all_playing.index(match["team1"][0]) if match["team1"][0] in all_playing else 0,
                                key=f"edit_m{i}_t1_p1"
                            )
                            new_t1_p2 = st.selectbox(
                                "Player 2",
                                options=all_playing,
                                index=all_playing.index(match["team1"][1]) if match["team1"][1] in all_playing else 0,
                                key=f"edit_m{i}_t1_p2"
                            )
                            st.session_state.current_matches[i]["team1"] = [new_t1_p1, new_t1_p2]
                        with col_vs:
                            st.markdown("<br><br><center><b>VS</b></center>", unsafe_allow_html=True)
                        with col_t2:
                            st.write("**Team 2**")
                            new_t2_p1 = st.selectbox(
                                "Player 1",
                                options=all_playing,
                                index=all_playing.index(match["team2"][0]) if match["team2"][0] in all_playing else 0,
                                key=f"edit_m{i}_t2_p1"
                            )
                            new_t2_p2 = st.selectbox(
                                "Player 2",
                                options=all_playing,
                                index=all_playing.index(match["team2"][1]) if match["team2"][1] in all_playing else 0,
                                key=f"edit_m{i}_t2_p2"
                            )
                            st.session_state.current_matches[i]["team2"] = [new_t2_p1, new_t2_p2]

                    # Recalculate ratings
                    st.session_state.current_matches[i]["team1_avg_rating"] = calculate_team_avg(
                        st.session_state.players,
                        st.session_state.current_matches[i]["team1"]
                    )
                    st.session_state.current_matches[i]["team2_avg_rating"] = calculate_team_avg(
                        st.session_state.players,
                        st.session_state.current_matches[i]["team2"]
                    )

                    st.divider()

        else:
            # Table layout display mode
            num_matches = len(st.session_state.current_matches)
            if num_matches > 0:
                # Create columns for each court
                court_cols = st.columns(num_matches)
                
                for idx, match in enumerate(st.session_state.current_matches):
                    with court_cols[idx]:
                        match_type = "Singles" if match["is_singles"] else "Doubles"
                        rating_diff = abs(match["team1_avg_rating"] - match["team2_avg_rating"])
                        balance = "✅" if rating_diff <= 1 else "⚠️"
                        
                        # Court header
                        st.markdown(f"""
                        <div style="background: linear-gradient(135deg, #4CAF50 0%, #2E7D32 100%); 
                                    padding: 10px; border-radius: 10px 10px 0 0; text-align: center; color: white;">
                            <strong>Court {match['court_number']}</strong><br>
                            <small>{match_type} {balance}</small>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Team 1
                        team1_players = "<br>".join([
                            f"{p} ⭐{get_player_rating(st.session_state.players, p)}" 
                            for p in match["team1"]
                        ])
                        st.markdown(f"""
                        <div style="background: #e8f5e9; padding: 10px; text-align: center; border-left: 3px solid #4CAF50; color: black;">
                            {team1_players}
                            <br><small style="color: #666;">Avg: {match['team1_avg_rating']:.1f}</small>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # VS divider
                        st.markdown("""
                        <div style="background: #fff; padding: 5px; text-align: center; font-weight: bold; color: black;">
                            ⚔️ VS ⚔️
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Team 2
                        team2_players = "<br>".join([
                            f"{p} ⭐{get_player_rating(st.session_state.players, p)}" 
                            for p in match["team2"]
                        ])
                        st.markdown(f"""
                        <div style="background: #fff3e0; padding: 10px; text-align: center; 
                                    border-left: 3px solid #FF9800; border-radius: 0 0 10px 10px; color: black;">
                            {team2_players}
                            <br><small style="color: #666;">Avg: {match['team2_avg_rating']:.1f}</small>
                        </div>
                        """, unsafe_allow_html=True)

        # Waiting players
        if st.session_state.waiting_players:
            st.markdown("""
            <div class="waiting-card">
                <h4>⏳ Waiting for Next Round</h4>
            </div>
            """, unsafe_allow_html=True)
            waiting_text = ", ".join([
                f"{p} (⭐{get_player_rating(st.session_state.players, p)})"
                for p in st.session_state.waiting_players
            ])
            st.write(waiting_text)
            st.caption("These players will have priority in the next round")

    elif active_count < 2:
        st.info("Need at least 2 active (non-paused) players to generate matches")
    else:
        if st.session_state.is_admin:
            st.info("Click 'Generate Round' to create match assignments")
        else:
            st.info("🔒 Waiting for admin to generate matches")

# Round history (expandable)
if st.session_state.round_history:
    with st.expander("📜 Round History"):
        for round_data in reversed(st.session_state.round_history):
            st.subheader(f"Round {round_data['round']}")
            for match in round_data["matches"]:
                match_type = "Singles" if match["is_singles"] else "Doubles"
                team1_str = " & ".join(match["team1"])
                team2_str = " & ".join(match["team2"])
                st.write(f"**Court {match['court_number']}** ({match_type}): {team1_str} vs {team2_str}")
            if round_data.get("waiting"):
                st.caption(f"Waiting: {', '.join(round_data['waiting'])}")
            st.divider()
