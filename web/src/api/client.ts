import type {
  Artist,
  ArtistCreate,
  CandidateStatus,
  EventCandidate,
  EventCandidateCreate,
  NamuWikiTemplate,
  SongArticleInput,
  Source,
  SourceCreate,
  SpotifyAlbum,
  SpotifyAlbumDetail,
  SpotifyArtist,
  SpotifyRelationship,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api-proxy').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(body?.detail || `요청을 처리하지 못했습니다. (${response.status})`, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  artists: {
    list: () => request<Artist[]>('/artists'),
    create: (payload: ArtistCreate) =>
      request<Artist>('/artists', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: number, payload: Partial<ArtistCreate>) =>
      request<Artist>(`/artists/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (id: number) => request<void>(`/artists/${id}`, { method: 'DELETE' }),
    addSource: (artistId: number, payload: SourceCreate) =>
      request<Source>(`/artists/${artistId}/sources`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    removeSource: (artistId: number, sourceId: number) =>
      request<void>(`/artists/${artistId}/sources/${sourceId}`, { method: 'DELETE' }),
  },
  events: {
    list: (status?: CandidateStatus) =>
      request<EventCandidate[]>(
        `/event-candidates${status ? `?status_filter=${encodeURIComponent(status)}` : ''}`,
      ),
    create: (payload: EventCandidateCreate) =>
      request<EventCandidate>('/event-candidates', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
  },
  google: {
    connectUrl: (discordUserId: string) =>
      `${API_BASE}/auth/google/start?discord_user_id=${encodeURIComponent(discordUserId)}`,
  },
  namuwiki: {
    templates: () => request<NamuWikiTemplate[]>('/namuwiki/templates'),
    saveTemplate: (payload: Required<Pick<NamuWikiTemplate, 'template_id' | 'name'>> & {
      description?: string
      template_example: string
    }) =>
      request<NamuWikiTemplate>('/namuwiki/templates', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    render: (song: SongArticleInput) =>
      request<{ text: string }>('/namuwiki/song-article', {
        method: 'POST',
        body: JSON.stringify(song),
      }),
    renderWithSavedTemplate: (templateId: string, song: SongArticleInput, instruction?: string) =>
      request<{ text: string }>('/namuwiki/song-article/from-saved-template', {
        method: 'POST',
        body: JSON.stringify({
          template_id: templateId,
          song,
          extra_instruction: instruction || null,
        }),
      }),
  },
  spotify: {
    artists: () => request<SpotifyArtist[]>('/spotify/artists'),
    syncArtists: () => request<SpotifyArtist[]>('/spotify/artists/sync', { method: 'POST' }),
    discography: (artistId: number) =>
      request<SpotifyAlbum[]>(`/spotify/artists/${artistId}/discography`),
    album: (albumId: string) =>
      request<SpotifyAlbumDetail>(`/spotify/albums/${encodeURIComponent(albumId)}`),
    relationships: () => request<SpotifyRelationship[]>('/spotify/relationships'),
  },
}
