import { formatDistanceToNowStrict } from "date-fns";

export function timeAgo(iso: string) {
  return formatDistanceToNowStrict(new Date(iso), { addSuffix: true });
}
