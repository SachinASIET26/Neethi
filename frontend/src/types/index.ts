// ===================== AUTH TYPES =====================

export type UserRole = "citizen" | "lawyer" | "legal_advisor" | "police" | "admin";

export interface UserProfile {
  user_id: string;
  full_name: string;
  email: string;
  role: UserRole;
  bar_council_id?: string;
  police_badge_id?: string;
  organization?: string;
  created_at: string;
  query_count_today?: number;
  rate_limit_remaining?: number;
}

export interface RegisterRequest {
  full_name: string;
  email: string;
  password: string;
  role: UserRole;
  bar_council_id?: string;
  police_badge_id?: string;
  organization?: string;
}

export interface RegisterResponse {
  user_id: string;
  email: string;
  role: UserRole;
  created_at: string;
  message: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserProfile;
}

export interface RefreshResponse {
  access_token: string;
  expires_in: number;
}

// ===================== QUERY TYPES =====================

export interface QueryRequest {
  query: string;
  language?: string;
  include_precedents?: boolean;
}

export type VerificationStatus = "VERIFIED" | "PARTIALLY_VERIFIED" | "UNVERIFIED";
export type ConfidenceLevel = "high" | "medium" | "low";

export interface CitationResult {
  act_code: string;
  section_number: string;
  section_title?: string;
  verification: "VERIFIED" | "VERIFIED_INCOMPLETE" | "NOT_FOUND";
}

export interface PrecedentResult {
  case_name: string;
  year: string;
  court: string;
  citation?: string;
  verification: "VERIFIED" | "NOT_FOUND";
}

export interface QueryResponse {
  query_id: string;
  query: string;
  response: string;
  verification_status: VerificationStatus;
  confidence: ConfidenceLevel;
  citations: CitationResult[];
  precedents: PrecedentResult[];
  user_role: string;
  processing_time_ms: number;
  cached: boolean;
  disclaimer: string;
}

export interface QueryHistoryItem {
  query_id: string;
  query_text: string;
  verification_status: VerificationStatus;
  confidence: ConfidenceLevel;
  created_at: string;
}

export interface QueryHistoryResponse {
  total: number;
  queries: QueryHistoryItem[];
}

export interface FeedbackRequest {
  query_id: string;
  rating: number;
  feedback_type: "helpful" | "citation_wrong" | "hallucination" | "incomplete" | "language_issue";
  comment?: string;
}

// ===================== SSE EVENT TYPES =====================

export interface SSEAgentEvent {
  agent: string;
  message?: string;
  duration_ms?: number;
}

export interface SSETokenEvent {
  text: string;
}

export interface SSECitationEvent {
  act_code: string;
  section_number: string;
  status: string;
}

export interface SSECompleteEvent extends Omit<QueryResponse, "query" | "response"> { }

export interface SSEErrorEvent {
  code: string;
  detail: string;
}

// ===================== CASES TYPES =====================

export interface CaseSearchRequest {
  query: string;
  act_filter?: string;
  top_k?: number;
  from_year?: number;
  to_year?: number;
}

export interface CaseResult {
  case_name: string;
  citation: string;
  court: string;
  judgment_date: string;
  judges: string[];
  legal_domain: string;
  relevance_score: number;
  summary: string;
  sections_cited: string[];
}

export interface CaseSearchResponse {
  results: CaseResult[];
  total_found: number;
  search_time_ms: number;
}

export interface CaseAnalysisRequest {
  scenario: string;
  case_citation?: string;
  applicable_acts?: string[];
}

export interface IRACAnalysis {
  issue: string;
  rule: string;
  application: string;
  conclusion: string;
}

export interface CaseAnalysisResponse {
  irac_analysis: IRACAnalysis;
  applicable_sections: CitationResult[];
  applicable_precedents: Array<{
    case_name: string;
    year: string;
    relevance: string;
  }>;
  confidence: ConfidenceLevel;
  verification_status: VerificationStatus;
}

export interface CaseDetail {
  case_id: string;
  case_name: string;
  citation: string;
  court: string;
  judgment_date: string;
  judges: string[];
  full_text: string;
  sections_cited: string[];
  headnotes: string[];
  indexed_at: string;
}

export interface SimilarCasesRequest {
  query: string;
  top_k?: number;
  year_from?: number;
  year_to?: number;
  verdict_type?: string;
  case_type?: string;
}

export interface SimilarCase {
  point_id: string;
  case_title: string;
  petitioner: string;
  respondent: string;
  judges: string[];
  verdict_type: string;
  case_type: string;
  year?: number;
  date: string;
  citation: string;
  legal_sections: string[];
  summary: string;
  key_holdings: string[];
  indian_kanoon_url: string;
  relevance_score: number;
}

export interface SimilarCasesResponse {
  results: SimilarCase[];
  total_found: number;
  search_time_ms: number;
  collection: string;
}

// ===================== DOCUMENTS TYPES =====================

export interface TemplateInfo {
  template_id: string;
  template_name: string;
  description: string;
  required_fields: string[];
  optional_fields: string[];
  jurisdiction: string;
  language: string;
  access_roles: UserRole[];
}

export interface TemplateListResponse {
  templates: TemplateInfo[];
}

export interface DraftRequest {
  template_id: string;
  fields: Record<string, string>;
  language?: string;
  include_citations?: boolean;
}

export interface DraftResponse {
  draft_id: string;
  template_id: string;
  title: string;
  draft_text: string;
  verification_status: VerificationStatus;
  citations_used: CitationResult[];
  disclaimer: string;
  created_at: string;
  word_count: number;
}

export interface DraftUpdateRequest {
  fields: Record<string, string>;
}

// ===================== SECTIONS TYPES =====================

export interface ActInfo {
  act_code: string;
  act_name: string;
  short_name?: string;
  era?: string;
  effective_from?: string;
  superseded_by?: string[];
  superseded_on?: string;
  replaces?: string[];
  total_sections: number;
  indexed_sections: number;
}

export interface ActListResponse {
  acts: ActInfo[];
}

export interface SectionDetail {
  act_code: string;
  act_name: string;
  section_number: string;
  section_title: string;
  chapter: string;
  chapter_title: string;
  legal_text: string;
  is_offence: boolean;
  is_cognizable: boolean;
  is_bailable: boolean;
  triable_by: string;
  replaces?: Array<{ act_code: string; section_number: string }>;
  related_sections: string[];
  verification_status: VerificationStatus;
  extraction_confidence: number;
}

export interface NormalizeResponse {
  input: { act: string; section: string };
  mapped_to: { act: string; section: string } | null;
  new_section_title?: string;
  transition_type?: string;
  warning?: string;
  effective_from?: string;
  source?: string;
  message?: string;
}

export interface VerifyRequest {
  citations: Array<{ act_code: string; section_number: string }>;
}

export interface VerifyResponse {
  results: Array<{
    act_code: string;
    section_number: string;
    status: "VERIFIED" | "NOT_FOUND";
    section_title?: string;
    warning?: string;
  }>;
}

// ===================== RESOURCES TYPES =====================

export interface NearbyRequest {
  resource_type: "legal_aid" | "court" | "lawyer" | "police_station" | "notary";
  latitude?: number;
  longitude?: number;
  city?: string;
  state?: string;
  radius_km?: number;
  limit?: number;
}

export interface ResourceResult {
  name: string;
  address: string;
  phone?: string;
  website?: string;
  distance_km?: number;
  open_now?: boolean;
  services?: string[];
  rating?: number;
  maps_url?: string;
}

export interface NearbyResponse {
  resource_type: string;
  location?: { latitude: number; longitude: number };
  results: ResourceResult[];
  total_found: number;
  note?: string;
}

export interface EligibilityResponse {
  eligible: boolean;
  basis: string;
  entitlements: string[];
  contact: {
    authority: string;
    helpline: string;
    website: string;
  };
}

// ===================== TRANSLATION TYPES =====================

export interface TranslateTextRequest {
  text: string;
  source_language?: string;
  target_language: string;
  domain?: string;
}

export interface TranslateTextResponse {
  translated_text: string;
  source_language: string;
  target_language: string;
  preserved_terms: string[];
  confidence: number;
  provider: string;
}

export interface TranslateQueryRequest {
  query: string;
  source_language: string;
}

export interface TranslateQueryResponse {
  original_query: string;
  english_query: string;
  source_language: string;
  confidence: number;
}

// ===================== VOICE TYPES =====================

export interface STTResponse {
  transcript: string;
  language_code: string;
  confidence: number;
  duration_seconds: number;
}

export interface TTSRequest {
  text: string;
  target_language_code?: string;
  speaker?: string;
  pitch?: number;
  pace?: number;
  loudness?: number;
  speech_sample_rate?: number;
  enable_preprocessing?: boolean;
}

export interface VoiceAskResponse {
  transcript: string;
  response_text: string;
  verification_status: VerificationStatus;
  confidence: ConfidenceLevel;
  citations: CitationResult[];
  audio_base64?: string;
  language_code: string;
  disclaimer: string;
}

// ===================== ADMIN TYPES =====================

export interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  timestamp: string;
  components: Record<string, {
    status: string;
    latency_ms?: number;
    error?: string;
    impact?: string;
  }>;
  mistral_fallback_active: boolean;
  indexed_sections?: Record<string, number>;
}

export interface UserListItem {
  user_id: string;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  is_email_verified: boolean;
  query_count_today: number;
  created_at: string;
  updated_at: string;
}

export interface UserListResponse {
  total: number;
  users: UserListItem[];
}

export interface UserDetailResponse {
  user_id: string;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  is_email_verified: boolean;
  bar_council_id?: string;
  police_badge_id?: string;
  organization?: string;
  query_count_today: number;
  total_queries: number;
  total_drafts: number;
  created_at: string;
  updated_at: string;
}

export interface UserUpdateRequest {
  role?: UserRole;
  is_active?: boolean;
}

export interface RoleCount {
  role: string;
  count: number;
}

export interface AdminStats {
  total_users: number;
  active_users: number;
  users_by_role: RoleCount[];
  total_queries_today: number;
  total_queries_all_time: number;
  total_drafts: number;
  recent_signups_7d: number;
}

export interface ActivityItem {
  query_id: string;
  user_id: string;
  user_name: string;
  user_email: string;
  user_role: string;
  query_text: string;
  verification_status?: string;
  confidence?: string;
  processing_time_ms?: number;
  cached: boolean;
  created_at: string;
}

export interface ActivityResponse {
  total: number;
  activities: ActivityItem[];
}

// ===================== CONVERSATION TYPES =====================

export interface TurnRequest {
  session_id?: string;
  message: string;
  language?: string;
  action_id?: string;
}

export interface ActionSuggestion {
  id: string;
  label: string;
  icon: string;
  description: string;
}

export interface TurnResponse {
  session_id: string;
  turn_number: number;
  intent: string;
  response: string;
  suggestions: ActionSuggestion[];
  needs_clarification: boolean;
  verification_status?: VerificationStatus;
  confidence?: ConfidenceLevel;
  citations: CitationResult[];
  processing_time_ms: number;
  cached: boolean;
}

export interface SessionResponse {
  session_id: string;
  user_id: string;
  turn_count: number;
  status: string;
  context: Record<string, unknown>;
  intent_history: string[];
  created_at: string;
  updated_at: string;
}

export interface SSEIntentEvent {
  intent: string;
  confidence: number;
}

export interface SSEClarificationEvent {
  questions: string[];
}

export interface SSEActionSuggestionsEvent {
  suggestions: ActionSuggestion[];
}

// ===================== DOCUMENT ANALYSIS TYPES =====================

// PageIndex returns relevant_contents as an array of arrays.
// Each inner array contains one or more content blocks for that excerpt.
export interface PageIndexContentBlock {
  section_title: string;
  physical_index: string;  // e.g. "<physical_index_1>" — a label, not a page number
  relevant_content: string;
}

export interface PageIndexNode {
  id: string;              // e.g. "0000", "0001"
  title: string;
  metadata: string[];
  relevant_contents: PageIndexContentBlock[][];  // array of arrays
}

export interface DocumentAnalysisResponse {
  doc_id: string;
  query: string;
  retrieved_nodes: PageIndexNode[];
  synthesized_answer: string;
  summary?: string;          // legacy — prefer synthesized_answer
  filename: string;
  processing_time_ms: number;
}

// ===================== API ERROR TYPES =====================

export interface APIError {
  detail: string;
  error_code?: string;
  request_id?: string;
}
