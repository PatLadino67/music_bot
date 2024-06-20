import os
import asyncio
import logging
from collections import deque
from threading import Thread
import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import keep_alive

# Configurar logging
logging.basicConfig(level=logging.INFO)

# Configura tus credenciales de Spotify desde variables de entorno
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')

spotify = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
    client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET))

# Configura los intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.presences = True
intents.members = True

# Configura el bot de Discord
bot = commands.Bot(command_prefix='-', intents=intents)

# Variables globales
music_queue = deque()
current_song = None
current_song_url = None
disconnect_timer = None
current_embed_color = discord.Color.green()  # Color predeterminado para embeds
autoplay = False  # Variable de control para autoplay

# Especifica la ruta completa a ffmpeg
FFMPEG_PATH = os.getenv('FFMPEG_PATH')

# Variables de control
loop = False
shuffle = False
playlists = {}

# Configuración de youtube_dl
ydl_opts = {
    'format':
    'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'quiet':
    True,
}


# Eventos del bot
@bot.event
async def on_ready():
    logging.info(f'Bot {bot.user} está listo y conectado!')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(
            description=
            "⚠️ Argumento requerido faltante. Por favor, revisa el uso del comando.",
            color=discord.Color.red()))
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send(embed=discord.Embed(
            description=
            "⚠️ Comando no encontrado. Usa `-comandos` para ver la lista de comandos disponibles.",
            color=discord.Color.red()))
    else:
        await ctx.send(embed=discord.Embed(
            description="⚠️ Ocurrió un error al ejecutar el comando.",
            color=discord.Color.red()))
        raise error


# Funciones de búsqueda y reproducción
def search_youtube(query):
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            if info['entries']:
                return info['entries'][0]
            return None
        except Exception as e:
            logging.error(f"Error al buscar en YouTube: {e}")
            return None


def search_spotify(query):
    results = spotify.search(q=query, limit=1)
    if results['tracks']['items']:
        track = results['tracks']['items'][0]
        youtube_query = f"{track['name']} {track['artists'][0]['name']}"
        return search_youtube(youtube_query)
    return None


async def play_next(ctx):
    global current_song, current_song_url, autoplay
    if music_queue:
        next_song = music_queue.popleft()
        await play(ctx, query=next_song['query'], from_queue=True)
    elif autoplay:
        await add_random_song_to_queue(ctx)
        await play_next(ctx)
    else:
        current_song, current_song_url = None, None
        embed = discord.Embed(
            title="Cola terminada 🛑",
            description=
            "No quedan más canciones por reproducir.\nPuedes activar -autoplay para que la cola nunca acabe.",
            color=discord.Color.red())
        await ctx.send(embed=embed)
        start_disconnect_timer(ctx)


def start_disconnect_timer(ctx):
    global disconnect_timer
    if disconnect_timer:
        disconnect_timer.cancel()
    disconnect_timer = asyncio.get_event_loop().call_later(
        900, lambda: asyncio.ensure_future(disconnect_from_voice(ctx)))


async def disconnect_from_voice(ctx):
    if ctx.voice_client and not ctx.voice_client.is_playing() and len(
            ctx.voice_client.channel.members) == 1:
        await ctx.voice_client.disconnect()
        await ctx.send(
            embed=discord.Embed(description="Desconectado por inactividad.",
                                color=discord.Color.orange()))


async def add_random_song_to_queue(ctx):
    youtube_result = search_youtube("recommended song")
    if youtube_result:
        url = youtube_result['webpage_url']
        title = youtube_result['title']
        music_queue.append({'query': title, 'title': title, 'url': url})
        await ctx.send(embed=discord.Embed(
            description=
            f"🔄 Añadido a la cola automáticamente: [{title}]({url})",
            color=current_embed_color))


class MusicControls(discord.ui.View):

    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="⏯️", style=discord.ButtonStyle.primary)
    async def pause_resume(self, button: discord.ui.Button,
                           interaction: discord.Interaction):
        if self.ctx.voice_client.is_playing():
            self.ctx.voice_client.pause()
            await interaction.response.send_message("⏸️ Música pausada.",
                                                    ephemeral=True)
        else:
            self.ctx.voice_client.resume()
            await interaction.response.send_message("▶️ Música reanudada.",
                                                    ephemeral=True)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.primary)
    async def skip(self, button: discord.ui.Button,
                   interaction: discord.Interaction):
        self.ctx.voice_client.stop()
        await interaction.response.send_message("⏭️ Saltando canción...",
                                                ephemeral=True)

    @discord.ui.button(label="🔁", style=discord.ButtonStyle.primary)
    async def toggle_loop(self, button: discord.ui.Button,
                          interaction: discord.Interaction):
        global loop
        loop = not loop
        status = "activado" if loop else "desactivado"
        await interaction.response.send_message(f"🔁 Loop {status}.",
                                                ephemeral=True)


# Comandos del bot
@bot.command(aliases=['j'])
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send(embed=discord.Embed(
            description=f"Conectado al canal de voz: {channel.name}",
            color=discord.Color.green()))
    else:
        await ctx.send(
            embed=discord.Embed(description="⚠️ No estás en un canal de voz!",
                                color=discord.Color.red()))


@bot.command(aliases=['l'])
async def leave(ctx):
    if ctx.voice_client:
        await ctx.guild.voice_client.disconnect()
        await ctx.send(
            embed=discord.Embed(description="Desconectado del canal de voz.",
                                color=discord.Color.blue()))
    else:
        await ctx.send(
            embed=discord.Embed(description="⚠️ No estoy en un canal de voz!",
                                color=discord.Color.red()))


@bot.command(aliases=['p'])
async def play(ctx, *, query, from_queue=False):
    global current_song, current_song_url
    youtube_result = search_youtube(query)

    if youtube_result:
        url = youtube_result['webpage_url']
        title = youtube_result['title']
        thumbnail = youtube_result.get('thumbnail', None)
        duration = youtube_result.get('duration', None)
    else:
        await ctx.send(embed=discord.Embed(
            description="⚠️ No se encontraron resultados en YouTube.",
            color=discord.Color.red()))
        return

    if ctx.voice_client is None:
        voice_channel = ctx.author.voice.channel
        await voice_channel.connect()

    def after_playing(error):
        if error:
            logging.error(f"Error después de reproducir: {error}")
        asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

    if ctx.voice_client.is_playing() and not from_queue:
        music_queue.append({
            'query': query,
            'title': title,
            'url': url,
            'thumbnail': thumbnail,
            'duration': duration
        })
        await ctx.send(embed=discord.Embed(
            description=f"Añadido a la cola: [{title}]({url})",
            color=current_embed_color))
    else:
        try:
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                URL = info['url']
        except Exception as e:
            logging.error(f"Error al reproducir la canción: {e}")
            await ctx.send(embed=discord.Embed(
                description=
                f"⚠️ No se pudo reproducir {title}. Buscando una alternativa...",
                color=discord.Color.red()))
            music_queue.appendleft({
                'query': query,
                'title': title,
                'url': url,
                'thumbnail': thumbnail,
                'duration': duration
            })
            await play_next(ctx)
            return

        current_song = title
        current_song_url = url
        try:
            ctx.voice_client.play(discord.FFmpegPCMAudio(
                URL, executable=FFMPEG_PATH),
                                  after=after_playing)
            ctx.voice_client.source = discord.PCMVolumeTransformer(
                ctx.voice_client.source)  # Añadido para manejar el volumen
            ctx.voice_client.source.volume = 0.5  # Volumen inicial
        except Exception as e:
            logging.error(f"Error al iniciar la reproducción: {e}")
            await ctx.send(embed=discord.Embed(
                description=
                f"⚠️ No se pudo iniciar la reproducción de {title}.",
                color=discord.Color.red()))
            await play_next(ctx)
            return

        embed = discord.Embed(title="Ahora suena 🎶",
                              description=f"[{title}]({url})",
                              color=current_embed_color)
        embed.add_field(name="Duración",
                        value=f"{duration // 60}:{duration % 60:02}",
                        inline=True)
        embed.add_field(name="En cola",
                        value=f"{len(music_queue)} canciones",
                        inline=True)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text=f"Pedido por {ctx.author.display_name}",
                         icon_url=ctx.author.avatar.url)
        view = MusicControls(ctx)
        await ctx.send(embed=embed, view=view)
        if not from_queue:
            start_disconnect_timer(ctx)


# Funciones de control adicionales
@bot.command(aliases=['lp'])
async def loop(ctx):
    global loop
    loop = not loop
    status = "activado" if loop else "desactivado"
    await ctx.send(embed=discord.Embed(description=f"🔁 Loop {status}.",
                                       color=current_embed_color))


@bot.command(aliases=['sh'])
async def shuffle(ctx):
    global shuffle
    shuffle = not shuffle
    status = "activado" if shuffle else "desactivado"
    await ctx.send(embed=discord.Embed(description=f"🔀 Shuffle {status}.",
                                       color=current_embed_color))


@bot.command(aliases=['ap'])
async def autoplay(ctx):
    global autoplay
    autoplay = not autoplay
    status = "activado" if autoplay else "desactivado"
    await ctx.send(embed=discord.Embed(description=f"🔄 Autoplay {status}.",
                                       color=current_embed_color))


@bot.command(aliases=['sp'])
async def save_playlist(ctx, *, name):
    global playlists, music_queue, current_song, current_song_url
    playlists[name] = list(music_queue)
    if current_song:
        playlists[name].insert(0, {
            'query': current_song,
            'title': current_song,
            'url': current_song_url
        })
    await ctx.send(
        embed=discord.Embed(description=f"💾 Playlist '{name}' guardada.",
                            color=current_embed_color))


@bot.command(aliases=['lpl'])
async def load_playlist(ctx, *, name):
    global playlists, music_queue
    if name in playlists:
        music_queue = deque(playlists[name])
        await ctx.send(
            embed=discord.Embed(description=f"📂 Playlist '{name}' cargada.",
                                color=current_embed_color))
        if not ctx.voice_client.is_playing():
            await play_next(ctx)
    else:
        await ctx.send(embed=discord.Embed(
            description=f"⚠️ Playlist '{name}' no encontrada.",
            color=discord.Color.red()))


@bot.command(aliases=['dp'])
async def delete_playlist(ctx, *, name):
    global playlists
    if name in playlists:
        del playlists[name]
        await ctx.send(
            embed=discord.Embed(description=f"🗑️ Playlist '{name}' eliminada.",
                                color=current_embed_color))
    else:
        await ctx.send(embed=discord.Embed(
            description=f"⚠️ Playlist '{name}' no encontrada.",
            color=discord.Color.red()))


@bot.command(aliases=['vp'])
async def view_playlists(ctx):
    if playlists:
        playlist_names = "\n".join(playlists.keys())
        message = await ctx.send(
            embed=discord.Embed(title="📋 Playlists guardadas",
                                description=playlist_names,
                                color=current_embed_color))
        await message.add_reaction("🗑️")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) == "🗑️"

        try:
            reaction, user = await bot.wait_for("reaction_add",
                                                timeout=60.0,
                                                check=check)
            if str(reaction.emoji) == "🗑️":
                await ctx.send(embed=discord.Embed(
                    description=
                    "Para eliminar una playlist, usa el comando `-delete_playlist <nombre>`",
                    color=discord.Color.orange()))
        except asyncio.TimeoutError:
            pass
    else:
        await ctx.send(
            embed=discord.Embed(description="⚠️ No hay playlists guardadas.",
                                color=discord.Color.orange()))


@bot.command(aliases=['s'])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send(embed=discord.Embed(
            description="⏭️ Saltando a la siguiente canción...",
            color=current_embed_color))
    else:
        await ctx.send(embed=discord.Embed(
            description="⚠️ No hay ninguna canción reproduciéndose.",
            color=discord.Color.orange()))


@bot.command(aliases=['np'])
async def nowplaying(ctx):
    if current_song:
        await ctx.send(embed=discord.Embed(
            description=
            f"🎵 Reproduciendo actualmente: [{current_song}]({current_song_url})",
            color=current_embed_color))
    else:
        await ctx.send(embed=discord.Embed(
            description="⚠️ No hay ninguna canción reproduciéndose.",
            color=discord.Color.orange()))


@bot.command(aliases=['q'])
async def queue(ctx):
    if music_queue:
        queue_list = "\n" + "\n".join([
            f"{idx + 1}. [{song['title']}]({song['url']})"
            for idx, song in enumerate(music_queue)
        ])
        await ctx.send(embed=discord.Embed(title="📃 Cola de Reproducción",
                                           description=queue_list,
                                           color=current_embed_color))
    else:
        await ctx.send(embed=discord.Embed(
            description="⚠️ La cola de reproducción está vacía.",
            color=discord.Color.orange()))


@bot.command(aliases=['v'])
async def volume(ctx, volume: int):
    if ctx.voice_client is None:
        return await ctx.send(
            embed=discord.Embed(description="⚠️ No estoy en un canal de voz.",
                                color=discord.Color.red()))
    if 0 <= volume <= 100:
        ctx.voice_client.source.volume = volume / 100
        await ctx.send(
            embed=discord.Embed(description=f"🔊 Volumen ajustado a {volume}%",
                                color=current_embed_color))
    else:
        await ctx.send(embed=discord.Embed(
            description=
            "⚠️ Por favor, proporciona un valor de volumen entre 0 y 100.",
            color=discord.Color.red()))


@bot.command(aliases=['rm'])
async def remove(ctx, index: int):
    if 0 <= index - 1 < len(music_queue):
        removed_song = music_queue.pop(index - 1)
        await ctx.send(embed=discord.Embed(
            description=f"❌ Eliminado de la cola: {removed_song['title']}",
            color=current_embed_color))
    else:
        await ctx.send(embed=discord.Embed(
            description="⚠️ Índice fuera de rango.", color=discord.Color.red())
                       )


@bot.command(aliases=['clr'])
async def clear(ctx):
    global music_queue
    music_queue.clear()
    await ctx.send(embed=discord.Embed(
        description="🧹 La cola de reproducción ha sido limpiada.",
        color=current_embed_color))


@bot.command(aliases=['mv'])
async def move(ctx, from_index: int, to_index: int):
    if 0 <= from_index - 1 < len(music_queue) and 0 <= to_index - 1 < len(
            music_queue):
        song = music_queue[from_index - 1]
        music_queue.remove(song)
        music_queue.insert(to_index - 1, song)
        message = await ctx.send(embed=discord.Embed(
            description=
            f"🔀 Movido {song['title']} de la posición {from_index} a la {to_index}.",
            color=current_embed_color))

        await message.add_reaction("⬆️")
        await message.add_reaction("⬇️")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["⬆️", "⬇️"]

        try:
            reaction, user = await bot.wait_for("reaction_add",
                                                timeout=60.0,
                                                check=check)
            if str(reaction.emoji) == "⬆️":
                if to_index - 1 > 0:
                    await move(ctx, from_index=to_index, to_index=to_index - 1)
            elif str(reaction.emoji) == "⬇️":
                if to_index < len(music_queue):
                    await move(ctx, from_index=to_index, to_index=to_index + 1)
        except asyncio.TimeoutError:
            await ctx.send(embed=discord.Embed(
                description=
                "⚠️ Tiempo de espera agotado para mover la canción.",
                color=discord.Color.red()))

    else:
        await ctx.send(
            embed=discord.Embed(description="⚠️ Índices fuera de rango.",
                                color=discord.Color.red()))


@bot.command(aliases=['cmds'])
async def comandos(ctx):
    commands_list = """
    **Comandos Disponibles:**
    `-join (j)`: Une el bot al canal de voz.
    `-leave (l)`: Desconecta el bot del canal de voz.
    `-play (p) <canción>`: Reproduce una canción o añade una canción a la cola.
    `-skip (s)`: Salta a la siguiente canción en la cola.
    `-nowplaying (np)`: Muestra la canción que se está reproduciendo actualmente.
    `-queue (q)`: Muestra la cola de reproducción.
    `-volume (v) <0-100>`: Ajusta el volumen de la reproducción.
    `-remove (rm) <número>`: Elimina una canción específica de la cola.
    `-clear (clr)`: Limpia toda la cola de reproducción.
    `-move (mv) <de> <a>`: Mueve una canción de una posición a otra en la cola.
    `-loop (lp)`: Activa o desactiva la repetición de la canción actual.
    `-shuffle (sh)`: Activa o desactiva la mezcla aleatoria de la cola.
    `-autoplay (ap)`: Activa o desactiva la reproducción automática.
    `-save_playlist (sp) <nombre>`: Guarda la cola actual como una playlist.
    `-load_playlist (lpl) <nombre>`: Carga una playlist guardada.
    `-delete_playlist (dp) <nombre>`: Elimina una playlist guardada.
    `-view_playlists (vp)`: Muestra todas las playlists guardadas.
    `-comandos (cmds)`: Muestra esta lista de comandos.
    """
    await ctx.send(embed=discord.Embed(description=commands_list,
                                       color=current_embed_color))


keep_alive.keep_alive()

# Ejecuta el bot con tu token desde variables de entorno
bot.run(os.getenv('DISCORD_TOKEN'))
