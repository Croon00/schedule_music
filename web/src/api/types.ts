export type SourceType = 'x' | 'official_site' | 'ticket_site' | 'rss' | 'other'
export type CandidateStatus = 'needs_review' | 'ready' | 'synced' | 'ignored'

export interface Source {
  id: number
  artist_id: number
  source_type: SourceType
  label: string | null
  value: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Artist {
  id: number
  name: string
  display_name: string | null
  notes: string | null
  created_at: string
  updated_at: string
  sources: Source[]
}

export interface ArtistCreate {
  name: string
  display_name?: string
  notes?: string
  x_username?: string
}

export interface SourceCreate {
  source_type: SourceType
  label?: string
  value: string
  is_active: boolean
}

export interface EventCandidate {
  id: number
  artist_id: number | null
  source_id: number | null
  title: string
  starts_at: string | null
  venue: string | null
  ticket_opens_at: string | null
  ticket_closes_at: string | null
  ticket_url: string | null
  price_text: string | null
  source_url: string | null
  raw_text: string | null
  status: CandidateStatus
  created_at: string
  updated_at: string
}

export type EventCandidateCreate = Omit<EventCandidate, 'id' | 'created_at' | 'updated_at'>

export interface NamuWikiTemplate {
  template_id: string
  name: string
  description: string | null
  template_example?: string
}

export interface SongArticleInput {
  title: string
  artist: string
  release_date?: string
  album?: string
  album_type?: string
  lyricist?: string
  composer?: string
  arranger?: string
  intro?: string
  youtube_url?: string
  categories: string[]
  lyrics: Array<{
    original?: string
    pronunciation_ko?: string
    translation_ko?: string
  }>
}

export interface SpotifyArtist {
  local_artist_id: number
  local_name: string
  spotify_artist_id: string | null
  spotify_name: string | null
  image_url: string | null
  spotify_url: string | null
  matched: boolean
}

export interface SpotifyAlbum {
  id: string
  name: string
  album_type: string
  release_date: string | null
  release_date_precision: string | null
  total_tracks: number
  image_url: string | null
  spotify_url: string | null
  artists: string[]
  artist_ids: string[]
}

export interface SpotifyTrack {
  id: string
  name: string
  track_number: number
  disc_number: number
  duration_ms: number | null
  explicit: boolean
  spotify_url: string | null
  artists: string[]
  artist_ids: string[]
}

export interface SpotifyAlbumDetail extends SpotifyAlbum {
  tracks: SpotifyTrack[]
}

export interface SpotifyRelationship {
  source_artist_id: number
  target_artist_id: number
  strength: number
  shared_releases: string[]
}
