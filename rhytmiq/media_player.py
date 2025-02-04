import random

from pathlib import Path
from threading import Thread
from time import sleep

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Button, ProgressBar, Static

from components.control_buttons import ControlButtons
from components.file_explorer import FileExplorer
from components.media_info import MediaInfo
from components.playlist import Playlist
from utils.constants import VOLUME_STEP, Loop, State, DEFAULT_VOLUME
from utils.helpers import get_metadata
from utils.playback import (decrease_volume, increase_volume, pause, play,
                            pygame, stop, unpause)

pygame.mixer.music.set_volume(DEFAULT_VOLUME)


class MediaPlayer(Container):
    """The main media player widget."""

    BINDINGS = [
        ("space", "toggle_play", "Toggle play"),
        ("s", "stop_song", "Stop"),
        ("n", "next_song", "Next song"),
        ("p", "previous_song", "Previous song"),
        ("+", "increase_volume", "Increase the volume"),
        ("-", "decrease_volume", "Decrease the volume"),
        ("l", "loop", "Change loop state"),
        ("r", "shuffle", "Toggle shuffle"),
    ]

    audio_title: str = reactive("No title available")
    artist_name: str = reactive("Unknown artist")
    album: str = reactive("No album info")
    duration: float = reactive(0)
    state: State = reactive(State.STOPPED)
    shuffle: bool = reactive(False)
    loop: Loop = reactive(Loop.NONE)
    volume: float = reactive(0.5)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.playing_song: Path = None
        self.current_playlist: list = None
        self.current_playlist_media: dict[str, str] = {}
        self.classes: str = "media-player-container"
        self.playing_from_playlist: bool = False
        self.monitor_thread: Thread = None
        self.running: bool = True
        self.state_switch: bool = False

        # Children
        self.file_explorer = FileExplorer(player=self, id="file-explorer")
        self.playlist = Playlist(player=self, id="playlist")

        self.media_info = MediaInfo(
            self.audio_title,
            self.artist_name,
            self.album,
            classes="media-info",
        )

        self.control_buttons = ControlButtons(
            classes="control-buttons-group",
        )

    def compose(self) -> ComposeResult:
        """Create child widgets for the player."""

        yield Horizontal(
            self.file_explorer,
            self.playlist,
            classes="files",
        )
        yield self.media_info
        yield self.control_buttons

    def play_song(self, media: str | Path = "", from_playlist: bool = False) -> None:
        """Manages playing new songs."""
        if not media:
            return

        self.state_switch = True
        self.playing_from_playlist = from_playlist

        if play(media):
            self.state = State.PLAYING
            self.playing_song = media
            self.audio_title, self.artist_name, self.album, self.duration = (
                get_metadata(media)
            )

            if self.monitor_thread is None or not self.monitor_thread.is_alive():
                self.monitor_thread = Thread(target=self.monitor_song_end, daemon=True)
                self.monitor_thread.start()
        else:
            self.next_song()
            self.notify("Unable to play the media file.")

        self.state_switch = False

    def play_from_playlist(self, media: tuple[str]) -> None:
        """Manages playing songs from the playlist."""
        self.current_playlist_media["title"], self.current_playlist_media["path"] = media

        self.play_song(self.current_playlist_media["path"], from_playlist=True)

    def monitor_song_end(self) -> None:
        """Monitor when a song ends."""
        while self.running:
            if self.state_switch:
                sleep(0.5)
                continue

            if self.state == State.PLAYING and not pygame.mixer.music.get_busy():
                self.handle_song_end()
                sleep(0.5)

    def handle_song_end(self) -> None:
        """Called when a song finishes playing."""

        if self.state == State.PAUSED:
            return

        if not self.playing_from_playlist:
            if self.loop != Loop.NONE:
                self.play_song(self.playing_song)
            else:
                self.state = State.STOPPED
            return

        if not self.playlist.songs:
            self.state = State.STOPPED
            return

        self.next_song()

    @on(Button.Pressed, "#play")
    def toggle_play_state(self) -> None:
        """Toggle between play and pause state."""
        if self.state == State.PLAYING:
            pause()
            self.state = State.PAUSED
        elif self.state == State.PAUSED:
            unpause()
            self.state = State.PLAYING
        elif self.state == State.STOPPED and self.playing_song is not None:
            self.play_song(self.playing_song, from_playlist=self.playing_from_playlist)

    @on(Button.Pressed, "#loop")
    def change_loop_state(self) -> None:
        """Toggle between the loop states (NONE, ONE and ALL)."""
        if self.loop == Loop.NONE:
            self.loop = Loop.ONE
        elif self.loop == Loop.ONE:
            self.loop = Loop.ALL
        else:
            self.loop = Loop.NONE

    @on(Button.Pressed, "#shuffle")
    async def toggle_shuffle_state(self) -> None:
        """Toggle between shuffle and unshuffle."""
        if not self.playlist.songs:
            return

        if not self.shuffle:
            self.current_playlist = list(self.playlist.songs.items())
            shuffled_playlist = self.current_playlist[:]
            random.shuffle(shuffled_playlist)
            self.playlist.songs = dict(shuffled_playlist)
        else:
            self.playlist.songs = dict(self.current_playlist)

        await self.playlist.clear()
        await self.playlist.populate()

        self.shuffle = not self.shuffle

    @on(Button.Pressed, "#next")
    def next_song(self) -> None:
        """Play the next media in the playlist."""
        if not self.playing_song:
            return

        if not self.playing_from_playlist and self.loop == Loop.NONE:
            stop()
            self.state = State.STOPPED
            return

        next_song_path = self.playing_song

        if self.playing_from_playlist and self.loop != Loop.ONE:
            titles = list(self.playlist.songs.keys())
            current_index = titles.index(self.current_playlist_media["title"])

            if current_index + 1 < len(titles):
                new_index = current_index + 1
            elif self.loop == Loop.ALL:
                new_index = 0
            else:
                stop()
                self.state = State.STOPPED
                return

            next_song_title = titles[new_index]
            next_song_path = self.playlist.songs[next_song_title]
            self.current_playlist_media["title"] = next_song_title
            self.current_playlist_media["path"] = next_song_path

        self.play_song(next_song_path, from_playlist=self.playing_from_playlist)

    @on(Button.Pressed, "#prev")
    def previous_song(self) -> None:
        """Play the previous media in the playlist."""
        if not self.playing_from_playlist and self.loop == Loop.NONE:
            stop()
            self.state = State.STOPPED
            return

        previous_song_path = self.playing_song

        if self.playing_from_playlist and self.loop != Loop.ONE:
            titles = list(self.playlist.songs.keys())
            current_index = titles.index(self.current_playlist_media["title"])

            if current_index > 0:
                new_index = current_index - 1
            elif self.loop == Loop.ALL:
                new_index = len(titles) - 1
            else:
                stop()
                self.state = State.STOPPED
                return

            previous_song_title = titles[new_index]
            previous_song_path = self.playlist.songs[previous_song_title]
            self.current_playlist_media["title"] = previous_song_title
            self.current_playlist_media["path"] = previous_song_path

        self.play_song(previous_song_path, from_playlist=self.playing_from_playlist)

    @on(Button.Pressed, "#decrease-volume")
    def decrease_media_volume(self):
        """Decrease the stream volume"""
        decrease_volume(VOLUME_STEP)
        self.volume = self.volume - VOLUME_STEP if self.volume > VOLUME_STEP else 0

    @on(Button.Pressed, "#increase-volume")
    def increase_media_volume(self):
        """Increase the stream volume"""
        increase_volume(VOLUME_STEP)
        self.volume = self.volume + VOLUME_STEP if self.volume + VOLUME_STEP < 1 else 1

    # WATCHERS for dynamic text reloading
    def watch_audio_title(self, old_value, new_value) -> None:
        try:
            self.query_one("#media-title", Static).update(new_value)
        except NoMatches:
            pass

    def watch_artist_name(self, old_value, new_value) -> None:
        try:
            self.query_one("#artist-name", Static).update(new_value)
        except NoMatches:
            pass

    def watch_album(self, old_value, new_value) -> None:
        try:
            self.query_one("#album", Static).update(new_value)
        except NoMatches:
            pass

    def watch_state(self, old_value, new_value) -> None:
        try:
            play_button = self.query_one("#play", Button)
            if self.state == State.PLAYING:
                play_button.label = "pause"
            else:
                play_button.label = "play"

        except NoMatches:
            pass

    def watch_shuffle(self, old_value, new_value) -> None:
        try:
            shuffle_button = self.query_one("#shuffle", Button)
            if self.shuffle:
                shuffle_button.label = "shuffle 🮱"
            else:
                shuffle_button.label = "shuffle"

        except NoMatches:
            pass

    def watch_loop(self, old_value, new_value) -> None:
        try:
            self.query_one("#loop", Button).label = f"loop {new_value.value}"
        except NoMatches:
            pass

    def watch_volume(self, old_value, new_value) -> None:
        try:
            self.query_one("#volume-progress", ProgressBar).update(progress=round(new_value*100))
        except NoMatches:
            pass

    # BINDING Actions
    def action_toggle_play(self) -> None:
        """Toggle between play and pause state from binding."""
        self.toggle_play_state()

    def action_next_song(self) -> None:
        """Play the next media"""
        self.next_song()

    def action_previous_song(self) -> None:
        """Play the previous media"""
        self.previous_song()

    def action_loop(self) -> None:
        """Change the loop state"""
        self.change_loop_state()

    async def action_shuffle(self) -> None:
        """Toggle shuffle state"""
        await self.toggle_shuffle_state()

    def action_stop_song(self) -> None:
        """Stop the lecture"""
        stop()
        self.state == State.STOPPED

    def action_increase_volume(self) -> None:
        """Increase the stream volume"""
        self.increase_media_volume()

    def action_decrease_volume(self) -> None:
        """Decrease the stream volume"""
        self.decrease_media_volume()
