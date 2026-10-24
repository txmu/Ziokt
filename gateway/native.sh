#!/usr/bin/env bash
set -euo pipefail
script=$1
export CORIUM_ROOT=$2 CORIUM_NETWORK_ID_OVERRIDE=$3
shift 3
source "$script"
load_config
case "$1" in
 protocol-publish)
  [[ "$2" =~ ^[a-f0-9]{64}$ ]] || exit 2
  size=$(python3 - "$3" "$2" <<'PY_PUBLIC_OBJECT'
import hashlib,os,stat,sys
fd=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW)
try:
 info=os.fstat(fd)
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077 or not 1<=info.st_size<=65536:raise ValueError('public object file rejected')
 raw=os.read(fd,65537)
 if len(raw)!=info.st_size or hashlib.sha256(raw).hexdigest()!=sys.argv[2]:raise ValueError('public object content address differs')
 print(len(raw))
finally:os.close(fd)
PY_PUBLIC_OBJECT
  ) || exit 1
  acquire_lock network; trap 'release_lock network' EXIT
  db_execute_safe "$DHT_DB" "INSERT OR REPLACE INTO local_chunks(hash,file_path,offset,size) VALUES (%s,%s,0,%d);" "$2" "$3" "$size" >/dev/null
  if dht_announce_chunk "$2" >/dev/null 2>&1; then
   printf '{"broadcast":"acknowledged_by_known_peers"}\n'
  else
   printf '{"broadcast":"pending"}\n'
  fi
  ;;
 topic) acquire_lock network; trap 'release_lock network' EXIT; forum_create_topic "$2" "$3" '' '' ;;
 post) acquire_lock network; trap 'release_lock network' EXIT; forum_create_post "$2" "$3" '' ;;
 engine-propose) acquire_lock network; trap 'release_lock network' EXIT; blockchain_create_transaction propose_new_compute_engine "$2" ;;
 cbb-post) acquire_lock network; trap 'release_lock network' EXIT; _cbb_post_and_broadcast "$2" ;;
 cbb-sync) acquire_lock network; trap 'release_lock network' EXIT; _cbb_sync_messages ;;
 cbb-state) _cbb_game_get_state "$2" ;;
 cbb-game) shift; corix_ceasefire game "$@" ;;
 bind)
  acquire_lock network; trap 'release_lock network' EXIT
  blockchain_create_transaction nns_update "$2" >/dev/null
  ;;
 register)
  acquire_lock network; trap 'release_lock network' EXIT
  cost=$(_nns_calculate_genesis_cost "$2" "$BLOCKCHAIN_DB")
  points=$(get_my_contribution_points)
  [ "$points" -ge "$cost" ] || exit 1
  data=$(jq -nc --arg name "$2" --arg root "$3" --argjson cost "$cost" '{domain_name:$name,target_hash:$root,proof_of_genesis_contribution:{burned_amount:$cost}}')
  blockchain_create_transaction nns_register "$data" >/dev/null
  ;;
 announce)
  acquire_lock network; trap 'release_lock network' EXIT
  case "$2" in
   forum_topic) data=$(jq -nc --arg id "$3" '{type:"forum_topic",topic_id:$id}') ;;
   forum_post) data=$(jq -nc --arg id "$3" --arg topic "$4" '{type:"forum_post",post_id:$id,topic_id:$topic}') ;;
   *) exit 2 ;;
  esac
  blockchain_create_transaction forum "$data" >/dev/null
  ;;
 *) exit 2 ;;
esac
