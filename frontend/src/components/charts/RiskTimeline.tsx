import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

interface RiskTimelineProps {
  /** 12 hourly failure-risk points (0-100), hour +1 through +12. */
  timeline: number[]
}

const CRITICAL_COLOR = '#f43f6e' // critical-500
const WARNING_COLOR = '#f59e0b' // warning/amber-500
const HEALTHY_COLOR = '#10b981' // healthy-500

/** Color a single risk bar by its projected failure-risk level. */
function riskColor(value: number): string {
  if (value >= 70) return CRITICAL_COLOR
  if (value >= 40) return WARNING_COLOR
  return HEALTHY_COLOR
}

/**
 * 12-point hourly risk timeline (Requirement 14.2). Each bar is the projected
 * failure risk (0-100) at that hour ahead, colored green/amber/red by level.
 */
export default function RiskTimeline({ timeline }: RiskTimelineProps) {
  const data = timeline.map((value, index) => ({
    hour: `+${index + 1}h`,
    value: Math.round(value * 10) / 10,
  }))

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 18, right: 8, bottom: 0, left: 8 }}>
        <XAxis
          dataKey="hour"
          tick={{ fill: '#475569', fontSize: 10 }}
          axisLine={{ stroke: '#e2e8f0' }}
          tickLine={false}
          interval={0}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fill: '#475569', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          width={28}
          tickFormatter={(v: number) => `${v}`}
        />
        <Tooltip
          cursor={{ fill: 'rgba(15,23,42,0.04)' }}
          contentStyle={{
            background: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: '#475569' }}
          formatter={(value: number) => [`${value}% risk`, 'Failure risk']}
        />
        <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={40}>
          {data.map((entry) => (
            <Cell key={entry.hour} fill={riskColor(entry.value)} />
          ))}
          <LabelList
            dataKey="value"
            position="top"
            formatter={(value: number) => `${value}`}
            fill="#475569"
            fontSize={9}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
