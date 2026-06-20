import { useParams } from 'react-router-dom'
import Placeholder from './Placeholder'

// TODO: Replaced by the XAI + forecast issue detail view in a later task (Requirement 18).
export default function IssueDetail() {
  const { id } = useParams<{ id: string }>()
  return <Placeholder title="Issue Detail" subtitle={`Issue: ${id ?? 'unknown'}`} />
}
