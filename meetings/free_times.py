import arrow

s1 = arrow.get('2013-05-05 08:00:00', 'YYYY-MM-DD HH:mm:ss')
e1 = arrow.get('2013-05-05 09:00:00', 'YYYY-MM-DD HH:mm:ss')
s2 = arrow.get('2013-05-05 10:00:00', 'YYYY-MM-DD HH:mm:ss')
e2 = arrow.get('2013-05-05 10:30:00', 'YYYY-MM-DD HH:mm:ss')
s3 = arrow.get('2013-05-05 11:00:00', 'YYYY-MM-DD HH:mm:ss')
e3 = arrow.get('2013-05-05 12:00:00', 'YYYY-MM-DD HH:mm:ss')
s4 = arrow.get('2013-05-05 08:30:00', 'YYYY-MM-DD HH:mm:ss')
e4 = arrow.get('2013-05-05 08:30:00', 'YYYY-MM-DD HH:mm:ss')

stti = arrow.get('2013-05-05 09:30:00', 'YYYY-MM-DD HH:mm:ss')
enti = arrow.get('2013-05-05 10:40:00', 'YYYY-MM-DD HH:mm:ss')

bbs = [[s1, e1], [s2, e2], [s3, e3]]
bbus = [[s2, e2],  [s1, e1], [s3, e3]]
mer = [[s1, e1], [s4, e4]]

def calculate_free_times(busy_blocks, start_time, end_time):
	'''
	Takes a start time, end time, and a list of lists that hold two arrow objects, a start and end time for the events. 
	'''
	merge(busy_blocks)
	completed_free_times = []
	start_time = str(start_time).replace('T', ' ')
	start_time = (arrow.get(start_time), 'YYYY-MM-DD HH:mm:ssZZ')
	end_time = str(end_time).replace('T', ' ')
	end_time = (arrow.get(end_time), 'YYYY-MM-DD HH:mm:ssZZ')
	print("start_time = " + str(start_time))
	print("end_time = " + str(end_time))
	for i in range(len(busy_blocks)-1):
		if busy_blocks[i][0] < start_time:
			del busy_blocks[i]
		# Should be unreachable
		elif busy_blocks[i][1] < start_time:
			del busy_blocks[i]
		elif busy_blocks[i][0] > end_time:
			del busy_blocks[i]
		elif busy_blocks[i][1] > end_time:
			del busy_blocks[i]
		else:
			# Block is in time range
			continue
	if start_time != busy_blocks[0][0]:
		completed_free_times.append([start_time, busy_blocks[0][0]])
	for i in range(len(busy_blocks)-1):
		completed_free_times.append([busy_blocks[i][1], busy_blocks[i+1][0]])
	if end_time != busy_blocks[-1][1]:
		completed_free_times.append([busy_blocks[-1][1], end_time])
	return completed_free_times

def sort(busy_blocks):
	'''
	Goes through a list of busy blocks of time and puts them in order based on their start times.
	'''
	busy_blocks.sort(key = lambda row: row[0])
	return busy_blocks

def merge(busy_blocks):
	'''
	Goes through a list of busy blocks of time and make sure than none of them overlap. If they do, 
	we merge them together so that the list is as small as possible.
	'''
	merged_busy_blocks = []
	finished_busy_blocks = []
	sort(busy_blocks)
	for block in busy_blocks:
		for checker in busy_blocks:
			if block[1] < checker[0] or checker[1] < block[0]:
				break
			elif block[0] > checker[0] and block[1] > checker[1]:
				block[0] = checker[0]
				merged_busy_blocks.append([block[0], block[1]])
				break
			elif block[1] > checker[0] and block[0] < checker[1]:
				block[1] = checker[1]
				merged_busy_blocks.append([block[0], block[1]])
				break
			elif block[0] < checker[0] and block[1] > checker[1]:
				merged_busy_blocks.append([block[0], block[1]])
				break
			elif block[0] > checker[0] and block[1] < checker[1]:
				merged_busy_blocks.append([checker[0], checker[1]])
				break
			elif block[0] == checker[0]:
				if block[1] >= checker[1]:
					merged_busy_blocks.append([block[0], block[1]])
				else:
					merged_busy_blocks.append([checker[0], checker[1]])
			elif block[1] == checker[1]:
				if block[0] <= checker[0]:
					merged_busy_blocks.append([block[0], block[1]])
				else:
					merged_busy_blocks.append([checker[0], checker[1]])
			else:
				print("PROBLEM IN CHECKER")
				break
	sort(merged_busy_blocks)
	for i in range(len(merged_busy_blocks)-1):
		if merged_busy_blocks[i][0] == merged_busy_blocks[i+1][0]:
			if merged_busy_blocks[i][1] >= merged_busy_blocks[i+1][1]:
				del merged_busy_blocks[i+1]
			else:
				del merged_busy_blocks[i]
		elif merged_busy_blocks[i][1] == merged_busy_blocks[i+1][1]:
			if merged_busy_blocks[i][0] <= merged_busy_blocks[i+1][0]:
				del merged_busy_blocks[i+1]
			else:
				del merged_busy_blocks[i]
