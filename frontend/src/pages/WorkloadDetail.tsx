import { useParams } from 'react-router-dom'
import Placeholder from './Placeholder'

// TODO: Replaced by the tabbed workload detail view in a later task (Requirement 17).
export default function WorkloadDetail() {
  const { id } = useParams<{ id: string }>()
  return <Placeholder title="Workload Detail" subtitle={`Workload: ${id ?? 'unknown'}`} />
}
